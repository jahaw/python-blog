#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''
Configuration
'''

import config_default

class Dict(dict):
    '''
    Simple dict but support access as x.y style.
    '''
    # **kw: 关键字参数(组织参数为dict)
    # *variable：可变参数(组织参数为tuple)
    def __init__(self, names=(), values=(), **kw):        
        # super(Dict, self)首先找到Dict的父类（就是类dict），然后 `把类Dict的对象self转换为类A的对象`
        super(Dict, self).__init__(**kw)
        # zip(a,b)zip()函数分别从a和b依次各取出一个元素组成元组，再将依次组成的元组组合成一个新的迭代器--新的zip类型数据(可以装换为list、tuple等)
        for k, v in zip(names, values):
            self[k] = v

    # __getattr__()：动态返回一个属性 用于处理调用不存在的类属性时的报错
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

def merge(defaults, override):
    r = {}
    for k, v in defaults.items():
        if k in override:
            if isinstance(v, dict):
                r[k] = merge(v, override[k])
            else:
                r[k] = override[k]
        else:
            r[k] = v
    return r

def toDict(d):
    D = Dict()
    for k, v in d.items():
        D[k] = toDict(v) if isinstance(v, dict) else v
    return D

configs = config_default.configs

try:
    import config_override
    # merge `dev and pro` database config
    configs = merge(configs, config_override.configs)
except ImportError:
    pass

configs = toDict(configs)
