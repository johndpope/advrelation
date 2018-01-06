## TODO

- Tensor2Tensor

## Candidate Methods

- attention context
- attention pooling
- adversarial, vadv unsurpervised
- focal loss
- scaled softmax, scaled attention
- relation net

## src

- src: SemEval binary MTL
- src1: SemEval + imdb + DBpedia
- src-adv: adv_text
- src-mem: memory attention
- src3: Fudan-MTL
- src4: merge fudan-data into one dataset

## [Tensor2Tensor](https://tensorflow.github.io/tensor2tensor/overview.html)

- Data Generation
  * t2t-datagen: `Problem.generate_data(data_dir, tmp_dir)`
- Input Pipeline
  * `example_reading_spec`, `Problem.dataset`, `Problem.input_fn`
- Hparams
  * `p.input_modality`, `p.target_modality`
- Build Model
  * `T2TModel.estimator_model_fn`, `model.model_fn`, 
  * `model.bottom`, `model.body`,`model.top`, `model.loss`
  * `model.estimator_spec_train`, `model.estimator_spec_eval`

## Reference

- [分分钟带你杀入Kaggle Top 1%][1]
- [用深度学习解决大规模文本分类问题][2]
- [知乎看山杯夺冠记][3]
- [Deep Learning for NLP Best Practices][4]
- [Wide and Deep Model][9]

* [Relation Classification via Convolutional Deep Neural Network][5]
* [Adversarial Multi-task Learning for Text Classification][6]
* [Attention-Based Bidirectional Long Short-Term Memory Networks for Relation Classification][7]
* [Bidirectional Recurrent Convolutional Neural Network for Relation Classification][8]
* [Adversarial training methods for semi-supervised text classification][10]
* [ Exploring the Limits of Language Modeling][11]

[1]: https://zhuanlan.zhihu.com/p/27424282
[2]: https://zhuanlan.zhihu.com/p/25928551
[3]: https://zhuanlan.zhihu.com/p/28923961
[4]: http://ruder.io/deep-learning-nlp-best-practices/index.html
[9]: https://research.googleblog.com/2016/06/wide-deep-learning-better-together-with.html

[5]: http://www.aclweb.org/anthology/C14-1220
[6]: http://www.aclweb.org/anthology/P/P17/P17-1001.pdf
[7]: http://aclweb.org/anthology/P16-2034
[8]: http://aclweb.org/anthology/P16-1072
[10]: https://arxiv.org/pdf/1605.07725.pdf
[11]: https://arxiv.org/pdf/1602.02410.pdf
