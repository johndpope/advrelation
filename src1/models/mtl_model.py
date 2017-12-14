import tensorflow as tf
from tensorflow.python.framework import ops

from models.base_model import BaseModel

flags = tf.app.flags

flags.DEFINE_integer("num_imdb_class", 2, "number of classes for imdb labels")
flags.DEFINE_integer("num_semeval_class", 19, 
                                     "number of classes for semeval labels")
flags.DEFINE_integer("pos_num", 123, "number of position feature")
flags.DEFINE_integer("pos_dim", 5, "position embedding size")
flags.DEFINE_integer("num_filters", 100, "cnn number of output unit")
flags.DEFINE_integer('hidden_size', 30,
                     'Number of hidden units in imdb classification layer.')

flags.DEFINE_float("l2_coef", 0.01, "l2 loss coefficient")
flags.DEFINE_float("lrn_rate", 1e-3, "learning rate")
flags.DEFINE_float("keep_prob", 0.5, "dropout keep probability")

FLAGS = flags.FLAGS

FILTER_SIZES = [3, 4, 5]

class FlipGradientBuilder(object):
  '''Gradient Reversal Layer from https://github.com/pumpikano/tf-dann'''
  def __init__(self):
    self.num_calls = 0

  def __call__(self, x, l=1.0):
    grad_name = "FlipGradient%d" % self.num_calls
    @ops.RegisterGradient(grad_name)
    def _flip_gradients(op, grad):
      return [ tf.negative(grad) * l]
    
    g = tf.get_default_graph()
    with g.gradient_override_map({"Identity": grad_name}):
      y = tf.identity(x)
        
    self.num_calls += 1
    return y
    
flip_gradient = FlipGradientBuilder()


def linear_layer(name, x, in_size, out_size, is_regularize=False):
  with tf.variable_scope(name):
    loss_l2 = tf.constant(0, dtype=tf.float32)
    w = tf.get_variable('linear_W', [in_size, out_size], 
                      initializer=tf.truncated_normal_initializer(stddev=0.1))
    b = tf.get_variable('linear_b', [out_size], 
                      initializer=tf.constant_initializer(0.1))
    o = tf.nn.xw_plus_b(x, w, b) # batch_size, out_size
    if is_regularize:
      loss_l2 += tf.nn.l2_loss(w) + tf.nn.l2_loss(b)
    return o, loss_l2


class LinearLayer(tf.layers.Layer):
  '''inherit tf.layers.Layer to cache trainable variables
  '''
  def __init__(self, layer_name, out_size, is_regularize, **kwargs):
    self.layer_name = layer_name
    self.out_size = out_size
    self.is_regularize = is_regularize
    super(LinearLayer, self).__init__(**kwargs)
  
  def build(self, input_shape):
    in_size = input_shape[1]

    with tf.variable_scope(self.layer_name):
      w_init = tf.truncated_normal_initializer(stddev=0.1)
      b_init = tf.constant_initializer(0.1)

      self.w = self.add_variable('W', [in_size, self.out_size], initializer=w_init)
      self.b = self.add_variable('b', [self.out_size], initializer=b_init)

      super(LinearLayer, self).build(input_shape)

  def call(self, x):
    loss_l2 = tf.constant(0, dtype=tf.float32)
    o = tf.nn.xw_plus_b(x, self.w, self.b)
    if self.is_regularize:
        loss_l2 += tf.nn.l2_loss(self.w) + tf.nn.l2_loss(self.b)
    return o, loss_l2

class ConvLayer(tf.layers.Layer):
  '''inherit tf.layers.Layer to cache trainable variables
  '''
  def __init__(self, layer_name, filter_sizes, **kwargs):
    self.layer_name = layer_name
    self.filter_sizes = filter_sizes
    self.conv = {} # trainable variables for conv
    super(ConvLayer, self).__init__(**kwargs)
  
  def build(self, input_shape):
    input_dim = input_shape[2]

    with tf.variable_scope(self.layer_name):
      w_init = tf.truncated_normal_initializer(stddev=0.1)
      b_init = tf.constant_initializer(0.1)

      for fsize in self.filter_sizes:
        w_shape = [fsize, input_dim, 1, FLAGS.num_filters]
        b_shape = [FLAGS.num_filters]
        w_name = 'conv-W%d' % fsize
        b_name = 'conv-b%d' % fsize
        self.conv[w_name] = self.add_variable(
                                           w_name, w_shape, initializer=w_init)
        self.conv[b_name] = self.add_variable(
                                           b_name, b_shape, initializer=b_init)
    
      super(ConvLayer, self).build(input_shape)

  def call(self, x):
    x = tf.expand_dims(x, axis=-1)
    input_dim = x.shape.as_list()[2]
    conv_outs = []
    for fsize in self.filter_sizes:
      w_name = 'conv-W%d' % fsize
      b_name = 'conv-b%d' % fsize
      
      conv = tf.nn.conv2d(x,
                        self.conv[w_name],
                        strides=[1, 1, input_dim, 1],
                        padding='SAME')
      conv = tf.nn.relu(conv + self.conv[b_name]) # batch,max_len,1,filters
      conv_outs.append(conv)
    return conv_outs

def max_pool(conv_outs, max_len):
  pool_outs = []

  for conv in conv_outs:
    pool = tf.nn.max_pool(conv, 
                        ksize= [1, max_len, 1, 1], 
                        strides=[1, max_len, 1, 1], 
                        padding='SAME') # batch,1,1,filters
    pool_outs.append(pool)
    
  n = len(conv_outs)
  pools = tf.reshape(tf.concat(pool_outs, 3), [-1, n*FLAGS.num_filters])

  return pools

class MTLModel(BaseModel):
  '''Multi Task Learning'''

  def __init__(self, word_embed, semeval_data, imdb_data, is_train):
    # input data
    self.semeval_data = semeval_data
    self.imdb_data = imdb_data
    self.is_train = is_train

    # embedding initialization
    w_trainable = True if FLAGS.word_dim==50 else False
    self.word_embed = tf.get_variable('word_embed', 
                                      initializer=word_embed,
                                      dtype=tf.float32,
                                      trainable=w_trainable)
    pos_shape = [FLAGS.pos_num, FLAGS.pos_dim]  
    self.pos1_embed = tf.get_variable('pos1_embed', shape=pos_shape)
    self.pos2_embed = tf.get_variable('pos2_embed', shape=pos_shape)

    self.shared_layer = ConvLayer('conv_shared', FILTER_SIZES)
    self.shared_linear = LinearLayer('linear_shared', 2, True)
    with tf.variable_scope('semeval_graph'):
      self.build_semeval_graph()
    with tf.variable_scope('imdb_graph'):
      self.build_imdb_graph()

  def adversarial_loss(self, feature, label):
    '''make the task classifier cannot reliably predict the task based on 
    the shared feature
    Args:
      feature: shared feature
      label: task label
    '''
    feature = flip_gradient(feature)
    feature_size = feature.shape.as_list()[1]
    if self.is_train:
      feature = tf.nn.dropout(feature, FLAGS.keep_prob)

    # Map the features to 2 classes
    logits, loss_l2 = self.shared_linear(feature)

    loss_adv = tf.reduce_mean(
        tf.nn.softmax_cross_entropy_with_logits(labels=label, logits=logits))
    return loss_adv, loss_l2

  def build_semeval_graph(self):
    lexical, labels, sentence, pos1, pos2 = self.semeval_data

    # embedding lookup
    lexical = tf.nn.embedding_lookup(self.word_embed, lexical)
    lexical = tf.reshape(lexical, [-1, 6*FLAGS.word_dim])

    sentence = tf.nn.embedding_lookup(self.word_embed, sentence)
    pos1 = tf.nn.embedding_lookup(self.pos1_embed, pos1)
    pos2 = tf.nn.embedding_lookup(self.pos2_embed, pos2)

    # cnn model
    if self.is_train:
      sentence = tf.nn.dropout(sentence, FLAGS.keep_prob)
    sent_pos = tf.concat([sentence, pos1, pos2], axis=2)
    
    conv_layer = ConvLayer('conv_semeval', FILTER_SIZES)
    conv_out = conv_layer(sent_pos)
    conv_out = max_pool(conv_out, FLAGS.semeval_max_len)

    shared_out = self.shared_layer(sentence)
    shared_out = max_pool(shared_out, FLAGS.semeval_max_len)

    feature = tf.concat([lexical, conv_out, shared_out], axis=1)
    if self.is_train:
      feature = tf.nn.dropout(feature, FLAGS.keep_prob)

    # Map the features to 19 classes
    feature_size = feature.shape.as_list()[1]
    logits, loss_l2 = linear_layer('linear_semeval', 
                                  feature, 
                                  feature_size, 
                                  FLAGS.num_semeval_class, 
                                  is_regularize=True)

    xentropy = tf.nn.softmax_cross_entropy_with_logits(
                          labels=tf.one_hot(labels, FLAGS.num_semeval_class), 
                          logits=logits)
    loss_ce = tf.reduce_mean(xentropy)

    task_label = tf.one_hot(tf.ones_like(labels), 2)
    loss_adv, loss_adv_l2 = self.adversarial_loss(shared_out, task_label)

    self.semeval_loss = loss_ce + 0.01*loss_adv + FLAGS.l2_coef*(loss_l2+loss_adv_l2)

    self.semeval_pred = tf.argmax(logits, axis=1)
    acc = tf.cast(tf.equal(self.semeval_pred, labels), tf.float32)
    self.semeval_accuracy = tf.reduce_mean(acc)

  def build_imdb_graph(self):
    labels, sentence = self.imdb_data
    sentence = tf.nn.embedding_lookup(self.word_embed, sentence)

    if self.is_train:
      sentence = tf.nn.dropout(sentence, FLAGS.keep_prob)
    
    conv_layer = ConvLayer('conv_imdb', FILTER_SIZES)
    conv_out = conv_layer(sentence)
    conv_out = max_pool(conv_out, FLAGS.imdb_max_len)

    shared_out = self.shared_layer(sentence)
    shared_out = max_pool(shared_out, FLAGS.imdb_max_len)

    feature = tf.concat([conv_out, shared_out], axis=1)
    if self.is_train:
      feature = tf.nn.dropout(feature, FLAGS.keep_prob)

    # Map the features to 2 classes
    feature_size = feature.shape.as_list()[1]
    logits, loss_l2 = linear_layer('linear_imdb_1', feature, 
                                  feature_size, FLAGS.num_imdb_class, 
                                  is_regularize=True)
    
    # xentropy= tf.nn.sigmoid_cross_entropy_with_logits(
    #                               logits=tf.squeeze(logits), 
    #                               labels=tf.cast(labels, tf.float32))
    xentropy = tf.nn.softmax_cross_entropy_with_logits(
                          labels=tf.one_hot(labels, FLAGS.num_imdb_class), 
                          logits=logits)
    loss_ce = tf.reduce_mean(xentropy)

    task_label = tf.one_hot(tf.zeros_like(labels), 2)
    loss_adv, loss_adv_l2 = self.adversarial_loss(shared_out, task_label)

    self.imdb_loss = loss_ce + 0.01*loss_adv + FLAGS.l2_coef*(loss_l2+loss_adv_l2)

    # self.imdb_pred = tf.cast(tf.greater(tf.squeeze(logits), 0.5), tf.int64)
    self.imdb_pred = tf.argmax(logits, axis=1)
    acc = tf.cast(tf.equal(self.imdb_pred, labels), tf.float32)
    self.imdb_accuracy = tf.reduce_mean(acc)

  def build_train_op(self):
    if self.is_train:
      self.global_step = tf.Variable(0, trainable=False, dtype=tf.int32)
      self.semeval_train = optimize(self.semeval_loss, self.global_step)
      self.imdb_train = optimize(self.imdb_loss, self.global_step)

def optimize(loss, global_step):
  optimizer = tf.train.AdamOptimizer(FLAGS.lrn_rate)

  update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
  with tf.control_dependencies(update_ops):# for batch_norm
    train_op = optimizer.minimize(loss, global_step)
  return train_op

def build_train_valid_model(word_embed, 
                            semeval_train, semeval_test, 
                            imdb_train, imdb_test):
  with tf.name_scope("Train"):
    with tf.variable_scope('MTLModel', reuse=None):
      m_train = MTLModel(word_embed, semeval_train, imdb_train, is_train=True)
  with tf.name_scope('Valid'):
    with tf.variable_scope('MTLModel', reuse=True):
      m_valid = MTLModel(word_embed, semeval_test, imdb_test, is_train=False)
  return m_train, m_valid