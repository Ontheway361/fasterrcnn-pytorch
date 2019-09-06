#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Created on 2019/09/08
@author: relu
"""
import torch
from torch import nn
import torch.nn.functional as F
from collections import OrderedDict

from IPython import embed

class ExtraFPNBlock(nn.Module):
    """
    Base class for the extra block in the FPN.

    Arguments:
        results (List[Tensor]): the result of the FPN
        x (List[Tensor]): the original feature maps
        names (List[str]): the names for each one of the original feature maps

    Returns:
        results (List[Tensor]): the extended set of results of the FPN
        names   (List[str])   : the extended set of names for the results
    """
    def forward(self, results, x, names):
        pass


class LastLevelMaxPool(ExtraFPNBlock):
    """ Applies a max_pool2d on top of the last feature map """

    def forward(self, results, names):   # BUG

        names.append("pool")
        # kernel_size=1, stride=2, padding=0
        results.append(F.max_pool2d(results[-1], 1, 2, 0))
        return results, names


class LastLevelP6P7(ExtraFPNBlock):
    """
    This module is used in RetinaNet to generate extra layers, P6 and P7.
    """
    def __init__(self, in_channels, out_channels):
        super(LastLevelP6P7, self).__init__()
        self.p6 = nn.Conv2d(in_channels, out_channels, 3, 2, 1)
        self.p7 = nn.Conv2d(out_channels, out_channels, 3, 2, 1)
        for module in [self.p6, self.p7]:
            nn.init.kaiming_uniform_(module.weight, a=1)
            nn.init.constant_(module.bias, 0)
        self.use_P5 = in_channels == out_channels

    def forward(self, p, c, names):
        p5, c5 = p[-1], c[-1]
        x = p5 if self.use_P5 else c5
        p6 = self.p6(x)
        p7 = self.p7(F.relu(p6))
        p.extend([p6, p7])
        names.extend(["p6", "p7"])
        return p, names


class FPN(nn.Module):
    """
    Module that adds a FPN from on top of a set of feature maps.
    refer to : https://blog.csdn.net/On_theway10/article/details/86686999

    The feature maps are currently supposed to be in increasing depth order.

    The input to the model is expected to be an OrderedDict[Tensor], containing
    the feature maps on top of which the FPN will be added.

    Arguments:
        in_channels_list (list[int]): number of channels for each feature map that
            is passed to the module
        out_channels (int): number of channels of the FPN representation
        extra_blocks (ExtraFPNBlock or None): if provided, extra operations will
            be performed. It is expected to take the fpn features, the original
            features and the names of the original features as input, and returns
            a new list of feature maps and their corresponding names
    """

    def __init__(self, in_channels_list, out_channels, with_tmp=True):

        super(FPN, self).__init__()

        self.inner_blocks = nn.ModuleList()
        self.layer_blocks = nn.ModuleList()

        for in_channels in in_channels_list:
            if in_channels == 0:
                continue
            inner_block_module = nn.Conv2d(in_channels, out_channels, 1)
            layer_block_module = nn.Conv2d(out_channels, out_channels, 3, padding=1)
            self.inner_blocks.append(inner_block_module)
            self.layer_blocks.append(layer_block_module)

        # initialize parameters now to avoid modifying the initialization of top_blocks
        # self.children : just first children-nodes of root_node
        # self.module : DFS of root_node
        for m in self.children():

            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_uniform_(m.weight, a=1)
                nn.init.constant_(m.bias, 0)

        if with_tmp:
            self.extra_blocks = LastLevelMaxPool()


    def forward(self, x):
        """
        Computes the FPN for a set of feature maps.

        Arguments:
            x (OrderedDict[Tensor]): feature maps[bottom -> top]

        Returns:
            results (OrderedDict[Tensor]): feature maps after FPN layers.
                They are ordered from highest resolution first.
        """
        # unpack OrderedDict into two lists for easier handling
        names = list(x.keys())
        x = list(x.values())

        last_inner = self.inner_blocks[-1](x[-1])
        results = []
        results.append(self.layer_blocks[-1](last_inner))

        # from top to bottom
        layer_iter = zip(x[:-1][::-1], self.inner_blocks[:-1][::-1], self.layer_blocks[:-1][::-1])

        # the resolution of result from high to low
        for feature, inner_block, layer_block in layer_iter:

            if not inner_block:
                continue
            inner_lateral = inner_block(feature)
            feat_shape = inner_lateral.shape[-2:]
            inner_top_down = F.interpolate(last_inner, size=feat_shape, mode="nearest")
            last_inner = inner_lateral + inner_top_down
            results.insert(0, layer_block(last_inner))   # store-style : bottom to head

        if self.extra_blocks is not None:
            results, names = self.extra_blocks(results, names) # BUG

        # make it back an OrderedDict
        out = OrderedDict([(k, v) for k, v in zip(names, results)])

        return out
