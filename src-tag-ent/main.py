import os
import time
import sys
import tensorflow as tf
import numpy as np

from inputs import  dataset, semeval_v2
from models import rnn_model
import config as config_lib

# tf.set_random_seed(0)
# np.random.seed(0)

flags = tf.app.flags
flags.DEFINE_boolean('test', False, 'set True to test')
FLAGS = tf.app.flags.FLAGS
tf.logging.set_verbosity(tf.logging.INFO)


def train_semeval(config, session, m_train, m_valid, test_iter, vocab_tags):
  best_acc, best_epoch = 0., 0
  start_time = time.time()
  orig_begin_time = start_time
  
  for epoch in range(config.hparams.num_epochs):
    loss, tags_acc, rel_acc = m_train.train_epoch(session, 80)
    train_msg = 'train loss %.2f tags_acc %.2f rel_acc %.2f' % (loss, tags_acc, rel_acc)

    # epoch duration
    now = time.time()
    duration = now - start_time
    start_time = now

    # valid accuracy
    tags_acc, f1, rel_acc = m_valid.evaluate(session, test_iter, 28, vocab_tags.vocab2id)
    test_msg = 'test tag_acc %.2f f1 %.2f rel_acc %.2f' % (tags_acc, f1, rel_acc)

    if best_acc < rel_acc:
      best_acc = rel_acc
      best_epoch = epoch
      m_train.save(session, epoch)
    
    print("Epoch %d %s %s time %.2f" % 
             (epoch, train_msg, test_msg, duration))
    sys.stdout.flush()
  
  duration = time.time() - orig_begin_time
  duration /= 3600
  print('Done training, best_epoch: %d, best_acc: %.4f' % (best_epoch, best_acc))
  print('duration: %.2f hours' % duration)
  sys.stdout.flush()

def test(session, m_valid, test_iter, vocab_tags):
  
  m_valid.restore(session)
  preds, tags = m_valid.evaluate(session, test_iter, 28, vocab_tags.vocab2id, return_pred=True)
  preds = [vocab_tags.decode(x) for x in preds]
  tags = [vocab_tags.decode(x) for x in tags]
  # print(len(tags))
  # print(tags[0])

  with open('tags.txt', 'w') as f:
    for arr in tags:
      f.write(' '.join(arr)+'\n')
  with open('preds.txt', 'w') as f:
    for arr in preds:
      f.write(' '.join(arr)+'\n')
  # vimdiff tags.txt preds.txt

  # semeval_v2.write_results(pred_all)

def main(_):
  config = config_lib.get_config()
  embed = dataset.Embed(config.out_dir, config.trimmed_embed300_file, config.vocab_file)
  ini_word_embed = embed.load_embedding()

  semeval_record = semeval_v2.SemEvalCleanedRecordData(None,
        config.out_dir, config.semeval_train_record, config.semeval_test_record)
  
  vocab_tags = dataset.Label(config.semeval_dir, config.semeval_tags_file)
  

  with tf.Graph().as_default():
    train_iter = semeval_record.train_data(config.hparams.num_epochs, config.hparams.batch_size)
    test_iter = semeval_record.test_data(1, config.hparams.batch_size)

                                          
    train_data = train_iter.get_next()
    test_data = test_iter.get_next()

    m_train, m_valid = rnn_model.build_train_valid_model(config, 
                                          ini_word_embed, train_data, test_data)

    init_op = tf.group(tf.global_variables_initializer(),
                        tf.local_variables_initializer())# for file queue
    sess_config = tf.ConfigProto()
    sess_config.gpu_options.allow_growth = True

    for tensor in tf.trainable_variables():
      tf.logging.info(tensor.op.name)
    
    with tf.Session(config=sess_config) as sess:
      sess.run(init_op)
      print('='*80)

      # for batch in range(3):
      #   # (labels, lengths, sentence, tags) = sess.run(train_data)
      #   # print(sentence.shape, tags.shape)
      #   l, w = sess.run([onehot_tags, weights])
      #   print(l.shape, w.shape)
      #   print(w)

      # # sess.run(test_iter.initializer)
      # # for batch in range(28):
      # #   (labels, lengths, sentence, tags) = sess.run(test_data)
      # #   print(sentence.shape, tags.shape)
      # exit()

      if FLAGS.test:
        test(sess, m_valid, test_iter, vocab_tags)
      else:
        train_semeval(config, sess, m_train, m_valid, test_iter, vocab_tags)

if __name__ == '__main__':
  tf.app.run()
