import os
import re
import numpy as np
import tensorflow as tf
from collections import defaultdict
from collections import namedtuple

flags = tf.app.flags

flags.DEFINE_string("vocab_file", "data/generated/vocab.txt", 
                              "vocab of train and test data")

flags.DEFINE_string("google_embed300_file", 
                             "data/pretrain/embed300.google.npy", 
                             "google news word embeddding")
flags.DEFINE_string("google_words_file", 
                             "data/pretrain/google_words.lst", 
                             "google words list")
flags.DEFINE_string("trimmed_embed300_file", 
                             "data/generated/embed300.trim.npy", 
                             "trimmed google embedding")

flags.DEFINE_string("senna_embed50_file", 
                             "data/pretrain/embed50.senna.npy", 
                             "senna words embeddding")
flags.DEFINE_string("senna_words_file", 
                             "data/pretrain/senna_words.lst", 
                             "senna words list")
flags.DEFINE_string("trimmed_embed50_file", 
                             "data/generated/embed50.trim.npy", 
                             "trimmed senna embedding")
FLAGS = tf.app.flags.FLAGS # load FLAGS.word_dim

PAD_WORD = "<pad>"

# nltk.tokenize.regexp.WordPunctTokenizer
pattern = r'\d+|\w+|[^\w\s]+' 
regexp = re.compile(pattern)

def wordpunct_tokenizer(line):
  line = re.sub(r"[^A-Za-z0-9]", " ", line)
  line = re.sub(r"\s{2,}", " ", line)

  return regexp.findall(line)

def write_vocab(vocab):
  '''collect words in sentence'''
  with open(FLAGS.vocab_file, 'w') as f:
    f.write('%s\n' % PAD_WORD) # make sure the pad id is 0
    for w in sorted(list(vocab)):
      f.write('%s\n' % w)

def _load_vocab(vocab_file):
  # load vocab from file
  vocab = []
  with open(vocab_file) as f:
    for line in f:
      w = line.strip()
      vocab.append(w)

  return vocab

def load_embedding(embed_file=None):
  '''Load embeddings from file
  '''
  if embed_file is None:
    if FLAGS.word_dim == 50:
      embed_file   = FLAGS.trimmed_embed50_file
    elif FLAGS.word_dim == 300:
      embed_file   = FLAGS.trimmed_embed300_file
  
  embed = np.load(embed_file)
  return embed 

def load_vocab2id(vocab_file=None):
  if vocab_file is None:
    vocab_file = FLAGS.vocab_file
  
  vocab2id = {}
  vocab = _load_vocab(vocab_file)
  for id, token in enumerate(vocab):
    vocab2id[token] = id

  return vocab2id

def trim_embeddings():
  '''trim unnecessary words from original pre-trained word embedding'''
  if FLAGS.word_dim == 50:
    pretrain_embed_file = FLAGS.senna_embed50_file
    pretrain_words_file = FLAGS.senna_words_file
    trimed_embed_file   = FLAGS.trimmed_embed50_file
  elif FLAGS.word_dim == 300:
    pretrain_embed_file = FLAGS.google_embed300_file
    pretrain_words_file = FLAGS.google_words_file
    trimed_embed_file   = FLAGS.trimmed_embed300_file

  pretrain_embed    = load_embedding(pretrain_embed_file)
  pretrain_words2id = load_vocab2id(pretrain_words_file)

  word_embed=[]
  vocab = _load_vocab(FLAGS.vocab_file)
  for w in vocab:
    if w in pretrain_words2id:
      id = pretrain_words2id[w]
      word_embed.append(pretrain_embed[id])
    else:
      vec = np.random.normal(0,0.1,[FLAGS.word_dim])
      word_embed.append(vec)
  pad_id = -1
  word_embed[pad_id] = np.zeros([FLAGS.word_dim])

  word_embed = np.asarray(word_embed)
  np.save(trimed_embed_file, word_embed.astype(np.float32))
  
def _map_tokens_to_ids(raw_example, vocab2id):
  '''inplace convert sentence from a list of tokens to a list of ids
  Args:
    raw_example: an instance of Raw_Example._asdict()
    vocab2id: dict<token, id> {token0: id0, ...}
  '''
  sent_id = []
  for token in raw_example['sentence']:
    if token in vocab2id:
      tok_id = vocab2id[token]
      sent_id.append(tok_id)
  raw_example['sentence'] = sent_id

def _pad_or_truncate(raw_example, max_len, pad_id):
  '''inplace pad or truncate a sentence to max_len
  Args:
    raw_example: an instance of Raw_Example._asdict()
    max_len: int
    pad_id: token id of PAD_WORD
  '''
  # truncate if len(sentence) > max_len
  # else nothing happens
  raw_example['sentence'] = raw_example['sentence'][:max_len]

  # pad if len(sentence) < max_len
  # else nothing happens
  pad_n = max_len - len(raw_example['sentence'])
  raw_example['sentence'].extend(pad_n*[pad_id])
    
def write_as_tfrecord(raw_data, vocab2id, filename, max_len, build_func):
  '''convert the raw data to TFRecord format and write to disk

  Args:
    raw_data: a list of Raw_Example
    vocab2id: dict<token, id>
    filename: file to write in
    max_len: int, pad or truncate sentence to max_len
    build_func: function to convert Raw_Example to tf.train.SequenceExample
  '''
  writer = tf.python_io.TFRecordWriter(filename)
  pad_id = vocab2id[PAD_WORD]
  
  for raw_example in raw_data:
    raw_example = raw_example._asdict()

    _map_tokens_to_ids(raw_example, vocab2id)
    _pad_or_truncate  (raw_example, max_len, pad_id)
    
    example = build_func(raw_example)
    writer.write(example.SerializeToString())
  writer.close()
  del raw_data


def read_tfrecord(filename, epoch, batch_size, parse_func, shuffle=True):
  '''read TFRecord file to get batch tensors for tensorflow models

  Returns:
    a tuple of batched tensors
  '''
  with tf.device('/cpu:0'):
    dataset = tf.data.TFRecordDataset([filename])
    # Parse the record into tensors
    dataset = dataset.map(parse_func)
    dataset = dataset.repeat(epoch)
    if shuffle:
      dataset = dataset.shuffle(buffer_size=100)
    
    dataset = dataset.batch(batch_size)
    
    iterator = dataset.make_one_shot_iterator()
    batch = iterator.get_next()
    return batch


