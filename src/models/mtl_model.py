import random
import os
import tensorflow as tf
from tensorflow.python.framework import ops
from .common import *


# compile:
# TF_INC=$(python -c 'import tensorflow as tf; print(tf.sysconfig.get_include())')
# g++ -std=c++11 -shared grl_op.cc -o grl_op.so -fPIC -I $TF_INC -O2 -D_GLIBCXX_USE_CXX11_ABI=0

# load op library
op_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'grl_op.so')
grl_module = tf.load_op_library(op_path)

@ops.RegisterGradient("GrlOp")
def _grl_op_grad(op, grad):
  """The gradients for `grl_op` (gradient reversal layer).

  Args:
    op: The `grl_op` `Operation` that we are differentiating, which we can use
      to find the inputs and outputs of the original op.
    grad: Gradient with respect to the output of the `grl_op` op.

  Returns:
    Gradients with respect to the input of `grl_op`.
  """
  return [-grad]  # List of one Tensor, since we have one input


def cnn_forward_lite(name, sent_pos, max_len, num_filters, use_grl=False):
  with tf.variable_scope(name, reuse=None):
    input = tf.expand_dims(sent_pos, axis=-1)
    if use_grl:
      input = grl_module.grl_op(input)
    input_dim = input.shape.as_list()[2]

    # convolutional layer
    # pool_outputs = []
    # filter_size = random.choice([1,2,3,4,5])
    filter_size = 3
    with tf.variable_scope('conv-%s' % filter_size):
      conv_weight = tf.get_variable('W1', 
                            [filter_size, input_dim, 1, num_filters], 
                            initializer=tf.truncated_normal_initializer(stddev=0.1))
      conv_bias = tf.get_variable('b1', [num_filters], 
                            initializer=tf.constant_initializer(0.1))
      if use_grl:
        conv_weight = grl_module.grl_op(conv_weight)
        conv_bias = grl_module.grl_op(conv_bias)
      conv = tf.nn.conv2d(input,
                          conv_weight,
                          strides=[1, 1, input_dim, 1],
                          padding='SAME')
      # Batch normalization here
      conv = tf.nn.relu(conv + conv_bias) # batch_size, max_len, 1, num_filters
      pool = tf.nn.max_pool(conv, ksize= [1, max_len, 1, 1], 
                            strides=[1, max_len, 1, 1], padding='SAME') # batch_size, 1, 1, num_filters
      # pool_outputs.append(pool)
    # pools = tf.reshape(tf.concat(pool_outputs, 3), [-1, 3*num_filters])
    pools = tf.reshape(pool, [-1, num_filters])

    return pools

class MTLModel(object):
  '''
  Adversarial Multi-task Learning for Text Classification
  http://www.aclweb.org/anthology/P/P17/P17-1001.pdf
  '''
  def __init__(self, word_embed, word_dim, max_len, 
              pos_num, pos_dim, num_relations,
              keep_prob, filter_size, num_filters,
              lrn_rate, decay_steps, decay_rate, is_train):
    # input data
    self.sent_id = tf.placeholder(tf.int32, [None, max_len])
    self.pos1_id = tf.placeholder(tf.int32, [None, max_len])
    self.pos2_id = tf.placeholder(tf.int32, [None, max_len])
    self.lexical_id = tf.placeholder(tf.int32, [None, 6])
    self.rid = tf.placeholder(tf.int32, [None])
    # embedding initialization
    # xavier = tf.contrib.layers.xavier_initializer()
    word_embed = tf.get_variable('word_embed', initializer=word_embed, dtype=tf.float32)
    # word_embed = tf.get_variable('word_embed', [len(word_embed), word_dim], dtype=tf.float32)
    pos_embed = tf.get_variable('pos_embed', shape=[pos_num, pos_dim])
    relation = tf.one_hot(self.rid, num_relations)

    # # embedding lookup
    lexical = tf.nn.embedding_lookup(word_embed, self.lexical_id) # batch_size, 6, word_dim
    lexical = tf.reshape(lexical, [-1, 6*word_dim])

    sentence = tf.nn.embedding_lookup(word_embed, self.sent_id)   # batch_size, max_len, word_dim
    pos1 = tf.nn.embedding_lookup(pos_embed, self.pos1_id)       # batch_size, max_len, pos_dim
    pos2 = tf.nn.embedding_lookup(pos_embed, self.pos2_id)       # batch_size, max_len, pos_dim
    
    # learn features from data
    # adversarial loss
    sent_pos = tf.concat([sentence, pos1, pos2], axis=2)
    if is_train and keep_prob < 1:
        sent_pos = tf.nn.dropout(sent_pos, keep_prob)
    shared = cnn_forward_lite('cnn-shared', sent_pos, max_len, num_filters, use_grl=True)
    shared_size = shared.shape.as_list()[1]
    if is_train and keep_prob < 1:
        shared = tf.nn.dropout(shared, keep_prob)
    # Map the features to 19 classes
    logits, _ = linear_layer('linear_adv', shared, shared_size, num_relations)
    loss_adv = tf.reduce_mean(
        tf.nn.softmax_cross_entropy_with_logits(labels=relation, logits=logits))

    # 19 classifier, task related loss
    probs_buf = []
    task_features = []
    loss_task = tf.constant(0, dtype=tf.float32)
    for i in range(num_relations):
      sent_pos = tf.concat([sentence, pos1, pos2], axis=2)
      if is_train and keep_prob < 1:
        sent_pos = tf.nn.dropout(sent_pos, keep_prob)

      cnn_out = cnn_forward_lite('cnn-%d'%i, sent_pos, max_len, num_filters)
      # feature 
      task_features.append(cnn_out)
      feature = tf.concat([cnn_out, shared, lexical], axis=1)
      feature_size = feature.shape.as_list()[1]

      if is_train and keep_prob < 1:
        feature = tf.nn.dropout(feature, keep_prob)

      # Map the features to 2 classes
      logits, _ = linear_layer('linear_%d'%i, feature, feature_size, 2)

      probs = tf.nn.softmax(logits)
      probs_buf.append(probs)

      labels = tf.cast(tf.equal(self.rid, i), tf.int32) # (batch, 1)
      labels = tf.one_hot(labels, 2)  # (batch, 2)
      
      entropy = tf.reduce_mean(
          tf.nn.softmax_cross_entropy_with_logits(labels=labels, logits=logits))
      loss_task += entropy

    probs_buf = tf.stack(probs_buf, axis=1) # (r, batch, 2) => (batch, r, 2)
    predicts = tf.argmax(probs_buf[:,:, 1] - probs_buf[:,:,0], axis=1, output_type=tf.int32)

    accuracy = tf.equal(predicts, self.rid)
    accuracy = tf.reduce_mean(tf.cast(accuracy, tf.float32))


    # Orthogonality Constraints
    task_features = tf.stack(task_features, axis=1) # (r, batch, hsize) => (batch, r, hsize)
    shared = tf.expand_dims(shared, axis=2)# (batch, hsize, 1)
    loss_diff = tf.reduce_sum(
      tf.pow(tf.matmul(task_features, shared), 2)
    )

    self.logits = logits
    self.prediction = predicts
    self.accuracy = accuracy
    # self.loss = loss_task + 0.05*loss_adv + 0.01*loss_diff
    self.loss = loss_task + loss_adv + loss_diff

    if not is_train:
      return 

    # global_step = tf.train.get_or_create_global_step()
    global_step = tf.Variable(0, trainable=False, name='step', dtype=tf.int32)
    optimizer = tf.train.AdamOptimizer(lrn_rate)

    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
    with tf.control_dependencies(update_ops):# for batch_norm
      self.train_op = optimizer.minimize(self.loss, global_step)
    self.global_step = global_step
   