import tensorflow as tf
from models.base_model import * 
from models.attention import *
from models.residual import residual_net

flags = tf.app.flags

flags.DEFINE_integer("pos_num", 123, "number of position feature")
flags.DEFINE_integer("pos_dim", 5, "position embedding size")
flags.DEFINE_integer("num_hops", 1, "hop numbers of entity attention")
flags.DEFINE_float("l2_coef", 0.01, "l2 loss coefficient")
flags.DEFINE_float("dropout_rate", 0.5, "dropout probability")
flags.DEFINE_float("lrn_rate", 0.001, "learning rate")

FLAGS = flags.FLAGS

MAX_LEN = 97
NUM_CLASSES = 19
# NUM_POWER_ITER = 1
# SMALL_CONSTANT = 1e-6
KERNEL_SIZE = 3
NUM_FILTERS = 310

class CNNModel(BaseModel):

  def __init__(self, word_embed, semeval_data, is_adv, is_train):
    # input data
    self.is_train = is_train
    self.is_adv = is_adv

    self.he_normal = tf.keras.initializers.he_normal()
    self.regularizer = tf.contrib.layers.l2_regularizer(FLAGS.l2_coef)

    # embedding initialization
    self.vocab_size, self.word_dim = word_embed.shape
    self.word_embed = tf.get_variable('word_embed', 
                                      initializer= word_embed,
                                      dtype=tf.float32,
                                      trainable=False)
    pos_shape = [FLAGS.pos_num, FLAGS.pos_dim]  
    self.pos1_embed = tf.get_variable('pos1_embed', shape=pos_shape)
    self.pos2_embed = tf.get_variable('pos2_embed', shape=pos_shape)

    self.tensors = dict()

    with tf.variable_scope('semeval_graph'):
      self.build_semeval_graph(semeval_data)

  def body(self, data):
    (label, length, ent_pos, sentence, pos1, pos2) = data

    # sentence and pos from embedding
    sentence = tf.nn.embedding_lookup(self.word_embed, sentence)

    pos1 = tf.nn.embedding_lookup(self.pos1_embed, pos1)
    pos2 = tf.nn.embedding_lookup(self.pos2_embed, pos2)

    # conv
    sentence = tf.layers.dropout(sentence, FLAGS.dropout_rate, training=self.is_train)
    inputs = tf.concat([sentence, pos1, pos2], axis=2)
    conv_out = conv_block_v2(inputs, KERNEL_SIZE, NUM_FILTERS,
                            'conv_block1',training=self.is_train, 
                             initializer=self.he_normal)
    # pool_out = tf.layers.max_pooling1d(conv_out, MAX_LEN, MAX_LEN, padding='same')
    # pool_out1 = tf.squeeze(pool_out, axis=1)

    ent1, ent2, context = self.slice_ent_and_context(conv_out, ent_pos, length)
    pool_out2 = self.entity_attention(context, ent1, ent2)

    # pool_out = tf.concat([pool_out1, pool_out2], axis=1)
    pool_out = pool_out2

    body_out = tf.layers.dropout(pool_out, FLAGS.dropout_rate, training=self.is_train)
    return label, body_out

  def slice_ent_and_context(self, conv_out, ent_pos, length):
    '''
    Args
      conv_out: [batch, max_len, filters]
      ent_pos:  [batch, 4]
      length:   [batch]
    '''
    # slice ent1
    # -------(e1.first--e1.last)-------e2.first--e2.last-------
    begin1 = ent_pos[:, 0]
    size1 = ent_pos[:, 1] - ent_pos[:, 0] + 1
    ent1 = slice_batch(conv_out, begin1, size1)

    # slice ent2
    # -------e1.first--e1.last-------(e2.first--e2.last)-------
    begin2 = ent_pos[:, 2]
    size2 = ent_pos[:, 3] - ent_pos[:, 2] + 1
    ent2 = slice_batch(conv_out, begin2, size2)
    
    # slice context
    # (-------)e1.first--e1.last(-------)e2.first--e2.last(-------)
    size1 = ent_pos[:, 0]
    begin1 = tf.zeros_like(size1, dtype=tf.int32)

    begin2 = ent_pos[:, 1]+1
    size2 = ent_pos[:, 2] - ent_pos[:, 1] - 1

    begin3 = ent_pos[:, 3]+1
    size3 = length-ent_pos[:, 3]-1

    context = slice_batch_n(conv_out, [begin1, begin2, begin3], [size1, size2, size3])

    ent1.set_shape(tf.TensorShape([None, None, NUM_FILTERS]))
    ent2.set_shape(tf.TensorShape([None, None, NUM_FILTERS]))
    context.set_shape(tf.TensorShape([None, None, NUM_FILTERS]))

    return ent1, ent2, context
    
  def conv_shallow(self, inputs):
    conv_out = conv_block_v2(inputs, KERNEL_SIZE, NUM_FILTERS,
                            'conv_block1',training=self.is_train, 
                          initializer=self.he_normal, batch_norm=False)

    pool_out = tf.layers.max_pooling1d(conv_out, MAX_LEN, MAX_LEN, padding='same')
    pool_out = tf.squeeze(pool_out, axis=1)
    return pool_out

  def conv_deep(self, inputs):
    return residual_net(inputs, MAX_LEN, NUM_FILTERS, self.is_train)

  def entity_attention(self, context, ent1, ent2, num_hops=1):
    cont1 = context
    cont2 = context
    for i in range(num_hops):
      cont1 = multihead_attention(cont1, ent1, num_heads=10, 
                                  # dropout_rate=FLAGS.dropout_rate,
                                  is_training=self.is_train, scope='att1-%d'%i)
      cont2 = multihead_attention(cont2, ent2, num_heads=10, 
                                  # dropout_rate=FLAGS.dropout_rate,
                                  is_training=self.is_train, scope='att2-%d'%i)
      # cont1 = feedforward(cont1, num_units=[620, 310], scope='ffd1%d'%i)
      # cont2 = feedforward(cont2, num_units=[620, 310], scope='ffd2%d'%i)
      ent1 = cont1
      ent2 = cont2

    ent1 = tf.reduce_mean(ent1, axis=1) # (batch, embed)
    ent2 = tf.reduce_mean(ent2, axis=1)
    entities = tf.concat([ent1, ent2], axis=-1)
    # entities = tf.squeeze(entities, axis=1)
    
    return entities

  def top(self, body_out, labels):
    logits = tf.layers.dense(body_out, NUM_CLASSES, kernel_regularizer=self.regularizer)

    # Calculate Mean cross-entropy loss
    with tf.name_scope("loss"):
      one_hot = tf.one_hot(labels, NUM_CLASSES)
      # one_hot = label_smoothing(one_hot)
      cross_entropy = tf.nn.softmax_cross_entropy_with_logits_v2(labels=one_hot,
                                logits=logits)

      regularization_losses = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
      loss = tf.reduce_mean(cross_entropy) + sum(regularization_losses)

    return logits, loss

  def build_semeval_graph(self, data):
    labels, body_out = self.body(data)
    logits, loss = self.top(body_out, labels)

    # Accuracy
    with tf.name_scope("accuracy"):
      pred = tf.argmax(logits, axis=1)
      acc = tf.cast(tf.equal(pred, labels), tf.float32)
      acc = tf.reduce_mean(acc)

    self.tensors['acc'] = acc
    self.tensors['loss'] = loss
    self.tensors['pred'] = pred

  def build_train_op(self):
    if self.is_train:
      # self.train_op = tf.no_op()
      loss = self.tensors['loss']
      self.train_op = optimize(loss, FLAGS.lrn_rate)


def build_train_valid_model(model_name, word_embed,
                            semeval_train, semeval_test, 
                            is_adv, is_test):
  with tf.name_scope("Train"):
    with tf.variable_scope('CNNModel', reuse=None):
      m_train = CNNModel(word_embed, semeval_train, is_adv, is_train=True)
      m_train.set_saver(model_name)
      if not is_test:
        m_train.build_train_op()
  with tf.name_scope('Valid'):
    with tf.variable_scope('CNNModel', reuse=True):
      m_valid = CNNModel(word_embed, semeval_test, is_adv, is_train=False)
      m_valid.set_saver(model_name)
  return m_train, m_valid