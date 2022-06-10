# Copyright (c) 2022 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from functools import partial

import math
import numpy as np

import paddle
import paddle.fluid as fluid
from paddle.fluid import core
from paddle.optimizer import AdamW

__all__ = ['AdamWDL', ]


# file1

# Layerwise decay
def layerwise_lr_decay(decay_rate, name_dict, n_layers, param):
    """
    Args:
        decay_rate (float): 
            The layer-wise decay ratio.
        name_dict (dict): 
            The keys of name_dict is dynamic name of model while the value
            of name_dict is static name.
            Use model.named_parameters() to get name_dict.
        n_layers (int):
            Total number of layers in the transformer encoder.
    """
    ratio = 1.0
    static_name = name_dict[param.name]
    if "blocks" in static_name:
        idx = static_name.find("blocks.")
        layer = int(static_name[idx:].split(".")[1])
        ratio = decay_rate**(n_layers - layer)
    elif "embed" in static_name:
        ratio = decay_rate**(n_layers + 1)
    param.optimize_attr["learning_rate"] *= ratio


class AdamWDL(AdamW):
    r"""
    The AdamWDL optimizer is implemented based on the AdamW Optimization with dynamic lr setting.
    Generally it's used for transformer model.

    We use "layerwise_lr_decay" as default dynamic lr setting method of AdamWDL.
    “Layer-wise decay” means exponentially decaying the learning rates of individual 
    layers in a top-down manner. For example, suppose the 24-th layer uses a learning
    rate l, and the Layer-wise decay rate is α, then the learning rate of layer m 
    is lα^(24-m). See more details on: https://arxiv.org/abs/1906.08237.

    .. math::
        & t = t + 1
    
        & moment\_1\_out = {\beta}_1 * moment\_1 + (1 - {\beta}_1) * grad

        & moment\_2\_out = {\beta}_2 * moment\_2 + (1 - {\beta}_2) * grad * grad

        & learning\_rate = learning\_rate * \frac{\sqrt{1 - {\beta}_2^t}}{1 - {\beta}_1^t}

        & param\_out = param - learning\_rate * (\frac{moment\_1}{\sqrt{moment\_2} + \epsilon} + \lambda * param)

    Args:
        learning_rate (float|LRScheduler, optional): The learning rate used to update ``Parameter``.
            It can be a float value or a LRScheduler. The default value is 0.001.
        beta1 (float, optional): The exponential decay rate for the 1st moment estimates.
            It should be a float number or a Tensor with shape [1] and data type as float32.
            The default value is 0.9.
        beta2 (float, optional): The exponential decay rate for the 2nd moment estimates.
            It should be a float number or a Tensor with shape [1] and data type as float32.
            The default value is 0.999.
        epsilon (float, optional): A small float value for numerical stability.
            It should be a float number or a Tensor with shape [1] and data type as float32.
            The default value is 1e-08.
        parameters (list|tuple, optional): List/Tuple of ``Tensor`` to update to minimize ``loss``. \
            This parameter is required in dygraph mode. \
            The default value is None in static mode, at this time all parameters will be updated.
        weight_decay (float, optional): The weight decay coefficient, it can be float or Tensor. The default value is 0.01.
        apply_decay_param_fun (function|None, optional): If it is not None,
            only tensors that makes apply_decay_param_fun(Tensor.name)==True
            will be updated. It only works when we want to specify tensors.
            Default: None.
        grad_clip (GradientClipBase, optional): Gradient cliping strategy, it's an instance of
            some derived class of ``GradientClipBase`` . There are three cliping strategies
            ( :ref:`api_fluid_clip_GradientClipByGlobalNorm` , :ref:`api_fluid_clip_GradientClipByNorm` ,
            :ref:`api_fluid_clip_GradientClipByValue` ). Default None, meaning there is no gradient clipping.
        lazy_mode (bool, optional): The official Adam algorithm has two moving-average accumulators.
            The accumulators are updated at every step. Every element of the two moving-average
            is updated in both dense mode and sparse mode. If the size of parameter is very large,
            then the update may be very slow. The lazy mode only update the element that has
            gradient in current mini-batch, so it will be much more faster. But this mode has
            different semantics with the original Adam algorithm and may lead to different result.
            The default value is False.
        multi_precision (bool, optional): Whether to use multi-precision during weight updating. Default is false.  
        layerwise_decay (float, optional): The layer-wise decay ratio. Defaults to 1.0.
        n_layers (int, optional): The total number of encoder layers. Defaults to 12.
        set_param_lr_fun (function|None, optional): If it's not None, set_param_lr_fun() will set the the parameter 
            learning rate before it executes Adam Operator. Defaults to :ref:`layerwise_lr_decay`.
        name_dict (dict, optional): The keys of name_dict is dynamic name of model while the value
            of name_dict is static name. Use model.named_parameters() to get name_dict.
        name (str, optional): Normally there is no need for user to set this property.
            For more information, please refer to :ref:`api_guide_Name`.
            The default value is None.

    Examples:
        .. code-block:: python

            import paddle
            from paddlenlp.ops.optimizer import AdamWDL
            def simple_lr_setting(decay_rate, name_dict, n_layers, param):
                ratio = 1.0
                static_name = name_dict[param.name]
                if "weight" in static_name:
                    ratio = decay_rate**0.5
                param.optimize_attr["learning_rate"] *= ratio
            
            linear = paddle.nn.Linear(10, 10)

            name_dict = dict()
            for n, p in linear.named_parameters():
                name_dict[p.name] = n

            inp = paddle.rand([10,10], dtype="float32")
            out = linear(inp)
            loss = paddle.mean(out)

            adamwdl = AdamWDL(
                learning_rate=1e-4,
                parameters=linear.parameters(),
                set_param_lr_fun=simple_lr_setting,
                layerwise_decay=0.8,
                name_dict=name_dict)
            
            loss.backward()
            adamwdl.step()
            adamwdl.clear_grad()
    """

    def __init__(self,
                 learning_rate=0.001,
                 beta1=0.9,
                 beta2=0.999,
                 epsilon=1e-8,
                 parameters=None,
                 weight_decay=0.01,
                 apply_decay_param_fun=None,
                 grad_clip=None,
                 lazy_mode=False,
                 multi_precision=False,
                 layerwise_decay=1.0,
                 n_layers=12,
                 set_param_lr_fun=layerwise_lr_decay,
                 name_dict=None,
                 name=None):
        if not isinstance(layerwise_decay, float) and \
                not isinstance(layerwise_decay, fluid.framework.Variable):
            raise TypeError("coeff should be float or Tensor.")
        self.layerwise_decay = layerwise_decay
        self.n_layers = n_layers
        self.set_param_lr_fun = partial(set_param_lr_fun, layerwise_decay,
                                        name_dict, n_layers)
        super(AdamWDL, self).__init__(
            learning_rate=learning_rate,
            parameters=parameters,
            beta1=beta1,
            beta2=beta2,
            epsilon=epsilon,
            grad_clip=grad_clip,
            name=name,
            apply_decay_param_fun=apply_decay_param_fun,
            weight_decay=weight_decay,
            lazy_mode=lazy_mode,
            multi_precision=multi_precision)

    def _append_optimize_op(self, block, param_and_grad):
        if self.set_param_lr_fun is None:
            return super(AdamLW, self)._append_optimize_op(block,
                                                           param_and_grad)

        self._append_decoupled_weight_decay(block, param_and_grad)
        prev_lr = param_and_grad[0].optimize_attr["learning_rate"]
        self.set_param_lr_fun(param_and_grad[0])
        # excute Adam op
        res = super(AdamW, self)._append_optimize_op(block, param_and_grad)
        param_and_grad[0].optimize_attr["learning_rate"] = prev_lr
        return res


# file2
# import paddle 
# from paddle import optimizer as optim
# from util.adamw import AdamWDL as AdamW 

AdamW = AdamWDL

def create_optimizer(model, filter_bias_and_bn=True, num_layers=None, skip_list=None, decay_dict=None):
    # opt_lower = args.opt.lower()
    opt_lower = 'adamw'
    weight_decay = 0.05

    # weight_decay = args.weight_decay

    if weight_decay and filter_bias_and_bn:
        skip = {}
        if skip_list is not None:
            skip = skip_list
        elif hasattr(model, 'no_weight_decay'):
            skip = model.no_weight_decay()
        decay_dict = {
            param.name: not (len(param.shape) == 1 or name.endswith(".bias")
                             or name in skip_list)
            for name, param in model.named_parameters()
            if not 'teacher' in name
        } 

        parameters = [
            param for param in model.parameters()
            if 'teacher' not in param.name
        ]
        weight_decay = 0.
    else:
        parameters = model.parameters()

    #opt_args = dict(learning_rate=args.lr, weight_decay=weight_decay)
    opt_args = dict(learning_rate=2e-4, weight_decay=weight_decay)

    opt_args['parameters'] = parameters 
    if decay_dict is not None:
        opt_args['apply_decay_param_fun'] = lambda n: decay_dict[n]
    # if hasattr(args, 'opt_eps') and args.opt_eps is not None:
    #     opt_args['epsilon'] = args.opt_eps

    # if hasattr(args, 'opt_betas') and args.opt_betas is not None:
    #     opt_args['beta1'] = args.opt_betas[0]
    #     opt_args['beta2'] = args.opt_betas[1]
    opt_args['beta1'] = 0.9
    opt_args['beta2'] = 0.999

    layer_decay = 0.65
    opt_args['layerwise_decay'] = layer_decay
    name_dict = dict()
    for n, p in model.named_parameters():
        name_dict[p.name] = n
    opt_args['name_dict'] = name_dict 
    opt_args['n_layers'] = num_layers 

    # if hasattr(args, 'layer_decay') and args.layer_decay < 1.0:
    #     opt_args['layerwise_decay'] = args.layer_decay
    #     name_dict = dict()
    #     for n, p in model.named_parameters():
    #         name_dict[p.name] = n
    #     opt_args['name_dict'] = name_dict 
    #     opt_args['n_layers'] = num_layers 
    
    opt_split = opt_lower.split('_')
    opt_lower = opt_split[-1]

    optimizer = AdamW(**opt_args) 

    # if opt_lower == 'sgd' or opt_lower == 'nesterov':
    #     opt_args.pop('epsilon', None)
    #     optimizer = optim.Momentum(momentum=args.momentum, use_nesterov=True, **opt_args)
    # elif opt_lower == 'momentum':
    #     opt_args.pop('epsilon', None)
    #     optimizer = optim.SGD(momentum=args.momentum, use_nesterov=False, **opt_args)
    # elif opt_lower == 'adam':
    #     optimizer = optim.Adam(**opt_args)
    # elif opt_lower == 'adamw':
    #     optimizer = AdamW(**opt_args)
    # elif opt_lower == 'adadelta':
    #     optimizer = optim.Adadelta(**opt_args)
    # elif opt_lower == 'rmsprop':
    #     optimizer = optim.RMSprop(alpha=0.9, momentum=args.momentum, **opt_args)
    # else:
    #     assert False and "Invalid optimizer"
    #     raise ValueError

    return optimizer



def cosine_scheduler(base_value,
                     final_value,
                    #  epochs,
                     total_iters,
                    #  warmup_epochs=0,
                     start_warmup_value=0,
                     warmup_iters=-1):
    warmup_schedule = np.array([])
    # warmup_iters = warmup_epochs * niter_per_ep
    # warmup_iters = warmup_iters

    print("Set warmup steps = %d" % warmup_iters)
    if warmup_iters > 0:
        warmup_schedule = np.linspace(start_warmup_value, base_value,
                                      warmup_iters)

    iters = np.arange(total_iters - warmup_iters)

    schedule = np.array([
        final_value + 0.5 * (base_value - final_value) *
        (1 + math.cos(math.pi * i / (len(iters)))) for i in iters
    ])

    schedule = np.concatenate((warmup_schedule, schedule))

    assert len(schedule) == total_iters
    return schedule



def polynomial_scheduler(base_value,
                     final_value,
                    #  epochs,
                     total_iters,
                    #  warmup_epochs=0,
                     start_warmup_value=0,
                     warmup_iters=-1):
    warmup_schedule = np.array([])
    # warmup_iters = warmup_epochs * niter_per_ep
    # warmup_iters = warmup_iters

    print("Set warmup steps = %d" % warmup_iters)
    if warmup_iters > 0:
        warmup_schedule = np.linspace(start_warmup_value, base_value,
                                      warmup_iters)

    iters = total_iters - warmup_iters


    scheduler = paddle.optimizer.lr.PolynomialDecay(learning_rate=base_value, decay_steps=iters, end_lr=final_value,  verbose=False)

    values = []

    for _ in range(iters):
        values.append(scheduler.get_lr())
        scheduler.step()

    schedule = np.concatenate((warmup_schedule, values))

    assert len(schedule) == total_iters
    return schedule


if __name__ == '__main__':


    model = None

    num_layers = model.get_num_layers()
    skip_list = model.no_weight_decay()

    decay_dict = {
        param.name: not (len(param.shape) == 1 or name.endswith(".bias")
                         or name in skip_list)
        for name, param in model.named_parameters()
        if not 'teacher' in name
    } 

    skip_weight_decay_list = model.no_weight_decay()

    # if args.disable_weight_decay_on_rel_pos_bias:
    #     for i in range(num_layers):
    #         skip_weight_decay_list.add("blocks.%d.attn.relative_position_bias_table" % i)

    optimizer = create_optimizer(model, skip_list=skip_weight_decay_list, num_layers=num_layers, decay_dict=decay_dict)
