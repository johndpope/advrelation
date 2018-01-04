import tensorflow as tf
from models.base_model import * 

flags = tf.app.flags

flags.DEFINE_integer("pos_num", 123, "number of position feature")
flags.DEFINE_integer("pos_dim", 5, "position embedding size")
flags.DEFINE_float("l2_coef", 0.01, "l2 loss coefficient")
flags.DEFINE_float("keep_prob", 0.5, "dropout keep probability")

FLAGS = flags.FLAGS

MAX_LEN = 98
CLASS_NUM = 19
NUM_POWER_ITER = 1
SMALL_CONSTANT = 1e-6

class CNNModel(BaseModel):

  def __init__(self, word_embed, vocab_freq, semeval_data, is_adv, is_train):
    # input data
    self.is_train = is_train
    self.is_adv = is_adv

    # embedding initialization
    self.vocab_size, self.word_dim = word_embed.shape
    # self.word_dim = 50
    w_trainable = True if self.word_dim==50 else False
    
    initializer=word_embed
    # initializer= tf.random_normal_initializer(0.0, self.word_dim**-0.5)
    # shape = [8097, self.word_dim]
    self.word_embed = tf.get_variable('word_embed', 
                                      # shape=shape,
                                      initializer= initializer,
                                      dtype=tf.float32,
                                      trainable=w_trainable)
    # self.word_embed = self.normalize_embed(self.word_embed, vocab_freq)
    pos_shape = [FLAGS.pos_num, FLAGS.pos_dim]
    self.pos1_embed = tf.get_variable('pos1_embed', shape=pos_shape)
    self.pos2_embed = tf.get_variable('pos2_embed', shape=pos_shape)

    self.mem_toks = tf.get_variable('mem_toks', initializer=initializer, dtype=tf.float32)
    self.mem_pos1 = tf.get_variable('mem_pos1', shape=pos_shape)
    self.mem_pos2 = tf.get_variable('mem_pos2', shape=pos_shape)

    self.embed_dim = self.word_dim + 2* FLAGS.pos_dim
    self.conv_layer = ConvLayer('conv_semeval', FILTER_SIZES)
    self.linear_layer = LinearLayer('linear_semeval', 300+2*self.embed_dim, CLASS_NUM, True)

    self.tensors = dict()

    with tf.variable_scope('semeval_graph'):
      self.build_semeval_graph(semeval_data)

  def normalize_embed(self, emb, vocab_freqs):
    vocab_freqs = tf.constant(
          vocab_freqs, dtype=tf.float32, shape=[self.vocab_size, 1])
    weights = vocab_freqs / tf.reduce_sum(vocab_freqs)
    mean = tf.reduce_sum(weights * emb, 0, keep_dims=True)
    var = tf.reduce_sum(weights * tf.pow(emb - mean, 2.), 0, keep_dims=True)
    stddev = tf.sqrt(1e-6 + var)
    return (emb - mean) / stddev

  def bottom(self, data):
    (label, length, 
      sentence, position1, position2, 
      ent1_toks, ent1_pos1, ent1_pos2,
      ent2_toks, ent2_pos1, ent2_pos2,
      context, cont_pos1, cont_pos2) = data

    # sentence and pos from embedding
    sentence = tf.nn.embedding_lookup(self.word_embed, sentence)

    pos1 = tf.nn.embedding_lookup(self.pos1_embed, position1)
    pos2 = tf.nn.embedding_lookup(self.pos2_embed, position2)

    # entities, context and pos from memory
    ent1_toks = tf.nn.embedding_lookup(self.mem_toks, ent1_toks)
    ent2_toks = tf.nn.embedding_lookup(self.mem_toks, ent2_toks)
    context = tf.nn.embedding_lookup(self.mem_toks, context)

    ent1_pos1 = tf.nn.embedding_lookup(self.mem_pos1, ent1_pos1)
    ent1_pos2 = tf.nn.embedding_lookup(self.mem_pos2, ent1_pos2)
    ent2_pos1 = tf.nn.embedding_lookup(self.mem_pos1, ent2_pos1)
    ent2_pos2 = tf.nn.embedding_lookup(self.mem_pos2, ent2_pos2)
    cont_pos1 = tf.nn.embedding_lookup(self.mem_pos1, cont_pos1)
    cont_pos2 = tf.nn.embedding_lookup(self.mem_pos2, cont_pos2)

    # process entities and context
    context = tf.concat([context, cont_pos1, cont_pos2], axis=2)
    ent1 = tf.concat([ent1_toks, ent1_pos1, ent1_pos2], axis=2)
    ent2 = tf.concat([ent2_toks, ent2_pos1, ent2_pos2], axis=2)

    ent1 = tf.reduce_mean(ent1, axis=1) # (batch, embed)
    ent2 = tf.reduce_mean(ent2, axis=1)

    entities = tf.concat([ent1, ent2], axis=-1) # (batch, 2*embed)
    

    return label, length, sentence, pos1, pos2, entities, context

  def xentropy_logits_and_loss(self, lexical, sentence, pos1, pos2, labels, l2_coef=0.01):
    if self.is_train:
      sentence = tf.nn.dropout(sentence, FLAGS.keep_prob)
    sent_pos = tf.concat([sentence, pos1, pos2], axis=2)

    conv_out = self.conv_layer(sent_pos)
    pool_out = max_pool(conv_out, MAX_LEN)

    # lexical = tf.reshape(lexical, [-1, 6*self.word_dim])
    feature = tf.concat([lexical, pool_out], axis=1)
    if self.is_train:
      feature = tf.nn.dropout(feature, FLAGS.keep_prob)

    # Map the features to 19 classes
    logits, loss_l2 = self.linear_layer(feature)
    loss = l2_coef*loss_l2

    if labels is not None:
      xentropy = tf.nn.softmax_cross_entropy_with_logits(
                                    labels=tf.one_hot(labels, CLASS_NUM), 
                                    logits=logits)
      loss_ce = tf.reduce_mean(xentropy)
      loss += loss_ce

    return logits, loss
  
  def adv_example(self, input, loss):
    grad, = tf.gradients(
        loss,
        input,
        aggregation_method=tf.AggregationMethod.EXPERIMENTAL_ACCUMULATE_N)
    grad = tf.stop_gradient(grad)
    perturb = scale_l2(grad)
    return input + perturb

  def adversarial_loss(self, loss, lexical, sentence, pos1, pos2, labels):
    adv_lexical = self.adv_example(lexical, loss)
    adv_sentence = self.adv_example(sentence, loss)
    _, loss = self.xentropy_logits_and_loss(adv_lexical, adv_sentence, pos1, pos2, labels, l2_coef=0)
    return loss

  def kl_divergence_with_logits(self, q_logit, p_logit):
    # https://github.com/takerum/vat_tf
    q = tf.nn.softmax(q_logit)
    qlogq = tf.reduce_mean(tf.reduce_sum(q * logsoftmax(q_logit), 1))
    qlogp = tf.reduce_mean(tf.reduce_sum(q * logsoftmax(p_logit), 1))
    kl = qlogq - qlogp
    return kl

  def virtual_adversarial_loss(self, logits, lexical, length, sentence, pos1, pos2):
    # Stop gradient of logits. See https://arxiv.org/abs/1507.00677 for details.
    logits = tf.stop_gradient(logits)

    # Initialize perturbation with random noise.
    d_sent = tf.random_normal(shape=tf.shape(sentence))
    d_lex = tf.random_normal(shape=tf.shape(lexical))

    # Perform finite difference method and power iteration.
    # See Eq.(8) in the paper http://arxiv.org/pdf/1507.00677.pdf,
    # Adding small noise to input and taking gradient with respect to the noise
    # corresponds to 1 power iteration.
    agg_method = tf.AggregationMethod.EXPERIMENTAL_ACCUMULATE_N
    for _ in range(NUM_POWER_ITER):
      d_sent = scale_l2(mask_by_length(d_sent, length), SMALL_CONSTANT) 
      d_lex = scale_l2(d_lex, SMALL_CONSTANT)
      vadv_sent = sentence + d_sent
      vadv_lex = lexical + d_lex
      d_logits, _ = self.xentropy_logits_and_loss(vadv_lex, vadv_sent, pos1, pos2, None, l2_coef=0)

      kl = self.kl_divergence_with_logits(logits, d_logits)
      d_sent, = tf.gradients(kl, d_sent, aggregation_method=agg_method)
      d_sent = tf.stop_gradient(d_sent)
      d_lex, = tf.gradients(kl, d_lex, aggregation_method=agg_method)
      d_lex = tf.stop_gradient(d_lex)

    vadv_sent = sentence + scale_l2(d_sent)
    vadv_lex = lexical + scale_l2(d_lex)
    vadv_logits, _ = self.xentropy_logits_and_loss(vadv_lex, vadv_sent, pos1, pos2, None, l2_coef=0)

    return self.kl_divergence_with_logits(logits, vadv_logits)

  def word_attention(self, entities, context):
    '''from paper Effective Deep Memory Networks for Distant Supervised Relation Extraction
    Args: 
      entities: [batch, 2*d]
      context: [batch, len, d]
    '''
    batch = 100
    hop = 1

    self.w_att = tf.get_variable('w_att', [3*self.embed_dim, 1])
    self.b_att = tf.get_variable('b_att', [1])
    self.linear_att = LinearLayer('linear_att', 2*self.embed_dim, self.embed_dim, False)

    shape = tf.ones_like(tf.concat([context, context], axis=-1))
    
    for _ in range(hop):
      e3d = tf.expand_dims(entities, axis=1) # (batch, 1, 2*d)
      e_tile = shape * e3d
      x3d = tf.concat([e_tile, context], axis=-1) # (batch, len, 3d)

      w3d = tf.tile(tf.expand_dims(self.w_att, axis=0), [batch, 1, 1])# (batch, 3d, 1)
      g = tf.nn.tanh(tf.nn.xw_plus_b(x3d, w3d, self.b_att)) #(batch, len, 1)

      alpha = tf.nn.softmax(tf.squeeze(g)) # (batch, len)
      alpha = tf.expand_dims(alpha, axis=-1)
      att_out = tf.reduce_sum(alpha * context, axis=1) # (batch, d)

      linear_out, _ = self.linear_att(entities)
      linear_out = tf.nn.relu(linear_out)
      entities = tf.concat([linear_out, att_out], axis=1)

    return entities
    
  def build_semeval_graph(self, data):
    labels, length, sentence, pos1, pos2, entities, context = self.bottom(data)
    lexical = self.word_attention(entities, context)
    
    logits, loss = self.xentropy_logits_and_loss(lexical, sentence, pos1, pos2, labels)
    if self.is_adv:
      adv_loss = self.adversarial_loss(loss, lexical, sentence, pos1, pos2, labels)
      vadv_loss = self.virtual_adversarial_loss(logits, lexical, length, sentence, pos1, pos2)
      loss += adv_loss + 0.01 * vadv_loss

    pred = tf.argmax(logits, axis=1)
    acc = tf.cast(tf.equal(pred, labels), tf.float32)
    acc = tf.reduce_mean(acc)

    self.tensors['acc'] = acc
    self.tensors['loss'] = loss
    self.tensors['pred'] = pred

  def build_train_op(self):
    if self.is_train:
      self.train_ops = []

      loss = self.tensors['loss']
      self.train_op = optimize(loss, 0.001)


def build_train_valid_model(model_name, word_embed, vocab_freq,
                            semeval_train, semeval_test, 
                            is_adv, is_test):
  with tf.name_scope("Train"):
    with tf.variable_scope('CNNModel', reuse=None):
      m_train = CNNModel(word_embed, vocab_freq, semeval_train, is_adv, is_train=True)
      m_train.set_saver(model_name)
      if not is_test:
        m_train.build_train_op()
  with tf.name_scope('Valid'):
    with tf.variable_scope('CNNModel', reuse=True):
      m_valid = CNNModel(word_embed, vocab_freq, semeval_test, is_adv, is_train=False)
      m_valid.set_saver(model_name)
  return m_train, m_valid