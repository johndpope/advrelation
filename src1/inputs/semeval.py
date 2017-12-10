import os
import tensorflow as tf
from collections import defaultdict
from collections import namedtuple

flags = tf.app.flags

flags.DEFINE_string("train_file", "data/train.cln", 
                             "original training file")
flags.DEFINE_string("test_file", "data/test.cln", 
                             "original test file")

flags.DEFINE_string("train_record", "data/train.tfrecord", 
                             "training file of TFRecord format")
flags.DEFINE_string("test_record", "data/test.tfrecord", 
                             "Test file of TFRecord format")

flags.DEFINE_string("relations_file", "data/relations_new.txt", "relations file")
flags.DEFINE_string("results_file", "data/results.txt", "predicted results file")

FLAGS = flags.FLAGS


Raw_Example = namedtuple('Raw_Example', 'label entity1 entity2 sentence')
PositionPair = namedtuple('PosPair', 'first last')


def load_raw_data(filename):
  '''load raw data from text file, 

  return: a list of Raw_Example
  '''
  data = []
  with open(filename) as f:
    for line in f:
      words = line.strip().split(' ')
      
      sent = words[5:]

      label = int(words[0])

      entity1 = PositionPair(int(words[1]), int(words[2]))
      entity2 = PositionPair(int(words[3]), int(words[4]))

      example = Raw_Example(label, entity1, entity2, sent)
      data.append(example)
  return data

def build_semeval_vocab(raw_data, raw_test_data):
  '''collect words in sentence'''
  if not os.path.exists(FLAGS.vocab_file):
    vocab = set()
    for example in raw_train_data + raw_test_data:
      for w in example.sentence:
          vocab.add(w)

    with open(FLAGS.vocab_file, 'w') as f:
      for w in sorted(list(vocab)):
        f.write('%s\n' % w)
      f.write('%s\n' % PAD_WORD)

def _lexical_feature(raw_example):
  def _entity_context(e_idx, sent):
    ''' return [w(e-1), w(e), w(e+1)]
    '''
    context = []
    context.append(sent[e_idx])

    if e_idx >= 1:
      context.append(sent[e_idx-1])
    else:
      context.append(sent[e_idx])
    
    if e_idx < len(sent)-1:
      context.append(sent[e_idx+1])
    else:
      context.append(sent[e_idx])
    
    return context

    
  e1_idx = raw_example.entity1.first
  e2_idx = raw_example.entity2.first

  context1 = _entity_context(e1_idx, raw_example.sentence)
  context2 = _entity_context(e2_idx, raw_example.sentence)

  # ignore WordNet hypernyms in paper
  lexical = context1 + context2
  return lexical

def _position_feature(raw_example):
  def distance(n):
    '''convert relative distance to positive number
    -60), [-60, 60], (60
    '''
    # FIXME: FLAGS.pos_num
    if n < -60:
      return 0
    elif n >= -60 and n <= 60:
      return n + 61
    
    return 122

  e1_idx = raw_example.entity1.first
  e2_idx = raw_example.entity2.first

  position1 = []
  position2 = []
  length = len(raw_example.sentence)
  for i in range(length):
    position1.append(distance(i-e1_idx))
    position2.append(distance(i-e2_idx))
  
  return position1, position2

def build_sequence_example(raw_example):
  '''build tf.train.SequenceExample from Raw_Example
  context features : lexical, rid, direction (mtl)
  sequence features: sentence, position1, position2

  Args: 
    raw_example : type Raw_Example

  Returns:
    tf.trian.SequenceExample
  '''
  ex = tf.train.SequenceExample()

  lexical = _lexical_feature(raw_example)
  ex.context.feature['lexical'].int64_list.value.extend(lexical)

  rid = raw_example.label
  ex.context.feature['rid'].int64_list.value.append(rid)

  for word_id in raw_example.sentence:
    word = ex.feature_lists.feature_list['sentence'].feature.add()
    word.int64_list.value.append(word_id)
  
  position1, position2 = _position_feature(raw_example)
  for pos_val in position1:
    pos = ex.feature_lists.feature_list['position1'].feature.add()
    pos.int64_list.value.append(pos_val)
  for pos_val in position2:
    pos = ex.feature_lists.feature_list['position2'].feature.add()
    pos.int64_list.value.append(pos_val)

  return ex

def _parse_tfexample(serialized_example):
  '''parse serialized tf.train.SequenceExample to tensors
  context features : lexical, rid, direction (mtl)
  sequence features: sentence, position1, position2
  '''
  context_features={
                      'lexical'   : tf.FixedLenFeature([6], tf.int64),
                      'rid'    : tf.FixedLenFeature([], tf.int64)}
  sequence_features={
                      'sentence' : tf.FixedLenSequenceFeature([], tf.int64),
                      'position1'  : tf.FixedLenSequenceFeature([], tf.int64),
                      'position2'  : tf.FixedLenSequenceFeature([], tf.int64)}
  context_dict, sequence_dict = tf.parse_single_sequence_example(
                      serialized_example,
                      context_features   = context_features,
                      sequence_features  = sequence_features)

  sentence = sequence_dict['sentence']
  position1 = sequence_dict['position1']
  position2 = sequence_dict['position2']

  lexical = context_dict['lexical']
  rid = context_dict['rid']

  return lexical, rid, sentence, position1, position2

def write_results(predictions, relations_file, results_file):
  relations = []
  with open(relations_file) as f:
    for line in f:
      segment = line.strip().split()
      relations.append(segment[1])
  
  start_no = 8001
  with open(results_file, 'w') as f:
    for idx, id in enumerate(predictions):
      rel = relations[id]
      f.write('%d\t%s\n' % (start_no+idx, rel))