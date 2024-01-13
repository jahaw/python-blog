#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Object-Relational Mapping 技术 : 关系数据库的表结构映射到对象（一个类对应一个对象）
# asyncio：获取 EventLoop(消息循环)的引用，把需要执行的协程扔进EventLoop执行，实现异步IO

import asyncio, logging

# 为MySQL数据库提供了 异步IO(异步编程) 的驱动
import aiomysql

def log(sql, args=()):
    logging.info('SQL: %s' % sql)

@asyncio.coroutine
def create_pool(loop, **kw):
    # **kw:关键字参数   将传递的参数组成 dict 内部可用 kw 来访问参数
    logging.info('create database connection pool...')
    global __pool
    __pool = yield from aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),  # 自动提交事物
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )

@asyncio.coroutine
def select(sql, args, size=None):
    log(sql, args)
    global __pool
    # contextlib:实现上下文管理(),即可使用with语句
    with (yield from __pool) as conn:
        # yield from :在一个协程中调用另外一个协程并返回结果
        cur = yield from conn.cursor(aiomysql.DictCursor)
        # SQL语句占位符 `?`  MySQL  : `%s`
        yield from cur.execute(sql.replace('?', '%s'), args or ())
        if size:
            rs = yield from cur.fetchmany(size)  # 获取指定数量的记录
        else:
            rs = yield from cur.fetchall()  # 获取所有记录
        yield from cur.close()
        logging.info('rows returned: %s' % len(rs))
        return rs


# 用于 Insert(?)  Update Delete
@asyncio.coroutine
def execute(sql, args, autocommit=True):
    log(sql)
    with (yield from __pool) as conn:
        if not autocommit:
            yield from conn.begin()
        try:
            cur = yield from conn.cursor()
            yield from cur.execute(sql.replace('?', '%s'), args)
            # 返回影响的行数
            affected = cur.rowcount
            yield from cur.close()
            if not autocommit:
                yield from conn.commit()
        except BaseException as e:
            if not autocommit:
                yield from conn.rollback()
            raise
        return affected


# eg： create_args_string(2)  "?, ?"
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)



# Field类：负责保存数据库表的字段名和字段类型
class Field(object):

    # default参数:让ORM 自动填入缺省值，在调用save时自动计算
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


# varchar(M) ：保存 可变长的字符串  （节省空间）
# 映射varchar 的 StringField
class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        # 调用父类的方法，将 self 对象转换为 父类的 self 对象  并初始化 实例属性
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)



# ModelMetaclass(元类)
# 定义 metaclass ，创建类 ，创建实例


# 任何继承自Model的类（比如User），会自动通过ModelMetaclass扫描映射关系，并存储到自身的 `类属性`如__table__、__mappings__中
# __new__()方法接收到的参数依次是：
    # cls:   当前准备创建的类的对象
    # name:  类的名字
    # bases: 类继承的父类集合
    # atrrs: 类的方法集合

#　ModelMetaclass中，一共做了几件事情：
    # 排除掉对Model类的修改
    # 在当前类（比如User）中查找定义的类的所有属性，如果找到一个Field属性，就把它保存到一个__mappings__的dict中，同时从类属性中删除该Field属性，否则，容易造成运行时错误(实例的属性会遮盖类的同名属性)
    # 把表名保存到__table__中，这里简化为表名默认为类名    

#　参考链接：　 https://www.liaoxuefeng.com/wiki/0014316089557264a6b348958f449949df42a6d3a2e542c000/0014319106919344c4ef8b1e04c48778bb45796e0335839000
class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键: 
                    if primaryKey:
                        # 主键字段重复
                        # raise StandardError('Duplicate primary key for field: %s' % k)
                        raise ValueError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            # raise StandardError('Primary key not found.')
            raise ValueError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)

        # 转码 字段名
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))

        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名

        # 定义 sql 语句
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)


# 定义所有ORM映射的基类   使用metaclass = ModelMetaclass来定制 Model类
# 作用:它指示Python解释器在创建Model类时，要通过ModelMetaclass.__new__()来创建
class Model(dict, metaclass=ModelMetaclass):

    # __init__():初始化实例属性
    # 给实例绑定属性的方法: 通过 `实例变量 / self变量`    
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    @asyncio.coroutine
    def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = yield from select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    @asyncio.coroutine
    def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = yield from select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    @asyncio.coroutine
    def find(cls, pk):
        ' find object by primary key. '
        rs = yield from select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    @asyncio.coroutine
    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = yield from execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    @asyncio.coroutine
    def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = yield from execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    @asyncio.coroutine
    def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = yield from execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)
