#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging; logging.basicConfig(level=logging.INFO)

# asyncio:实现单线程并发的IO操作
# os:操作系统相关功能(处理文件和目录)

import asyncio, os, json, time
from datetime import datetime

# aiohttp:基于asyncio 实现的HTTP框架
from aiohttp import web

# Environment ： jinja2 模板的环境配置
# FileSystemLoader：文件系统加载器，用来加载模板路径
from jinja2 import Environment, FileSystemLoader

from config import configs
print("Database:",configs.db)

import orm
from coroweb import add_routes, add_static

from handlers import cookie2user, COOKIE_NAME

# 这个函数的功能是 初始化jinja2 模板，配置 jinja2 的环境
def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    # 设置模板解析需要用到的环境配置
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    # 从**kw中获取模板路径，如果没有则设置为None
    path = kw.get('path', None)
    if path is None:
        # 获取文件路径
        # os.path.abspath(__file__): 显示app.py的绝对路径
        # os.path.dirname(path): 返回该路径的目录部分
        # os.path.join(path,name): 连接目录与文件名或目录 `path/mane`  
        #　__file__ : app.py
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)

    # loader=FileSystemLoader(path):到哪个目录下加载模板文件
    env = Environment(loader=FileSystemLoader(path), **options)
    # {'datetime': <function datetime_filter at 0x0000000002062EA0>}
    
    # 过滤器
    filters = kw.get('filters', None)    
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f

    # 前面已经把jinja2的环境配置都赋值给了env，这里再把env存进app的dict中，这样app就知道要到哪儿找模板，怎么解析模板
    app['__templating__'] = env



# 当有http请求时输出请求信息
@asyncio.coroutine
def logger_factory(app, handler):
    @asyncio.coroutine
    def logger(request):
        logging.info('Request: %s %s' % (request.method, request.path))
        return (yield from handler(request))
    return logger



@asyncio.coroutine
def auth_factory(app, handler):
    @asyncio.coroutine
    def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = yield from cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
            return web.HTTPFound('/signin')
        return (yield from handler(request))
    return auth


# 解析POST的请求参数
@asyncio.coroutine
def data_factory(app, handler):
    @asyncio.coroutine
    def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = yield from request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = yield from request.post()
                logging.info('request form: %s' % str(request.__data__))
        return (yield from handler(request))
    return parse_data



# 
@asyncio.coroutine
def response_factory(app, handler):
    @asyncio.coroutine
    def response(request):
        logging.info('Response handler...')
        # 调用 handler 处理url请求，并返回响应结果
        r = yield from handler(request)
        # StreamResponse 是 aiohttp 定义 response 的基类 所有响应类型都继承自该类
        # StreamResponse：主要为流式数据设计
        if isinstance(r, web.StreamResponse):
            return r
        # 若响应内容为字节流，则将其作为应答的body部分，并设置响应类型为流型
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        # 若响应结果为字符串
        if isinstance(r, str):
            # 判断响应结果是否为重定向，若是，则返回重定向的地址
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            # 响应结果不是重定向，则以utf-8对字符串进行编码，作为body并设置相应的相应类型
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        # 若响应结果为字典，则获取它的模板属性，此处为jinja2.env(见init_jinja2)        
        if isinstance(r, dict):
            template = r.get('__template__')
            # 若不存在对应模板，则将字典调整为json格式返回，并设置响应类型为json            
            if template is None:
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            # 存在模板，则将套用模板，用request handler的结果进行渲染
            else:
                r['__user__'] = request.__user__
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        # 若响应结果为整型的
        # 此处 r 为状态码 即404,500等
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        # 若响应结果为元组，并且长度为 2
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            # t 为http状态码 m 为错误描述
            # 判断 t 是否满足100-600 的条件
            if isinstance(t, int) and t >= 100 and t < 600:
                # 返回状态码和错误描述
                return web.Response(t, str(m))
        # default:默认以字符串形式返回响应结果，设置类型为普通文本
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response



# 事件过滤器：返回日志创建的大概时间，用于显示在日志标题下面

# u'1分钟前'：对字符串 `1分钟前`进行unicode编码
# r'1分钟前'：对字符串 `1分钟前`不进行转码
# b'1分钟前'：字符串 `1分钟前`中每个字符只占一个字节
def datetime_filter(t):
    # 生成timestamp
    delta = int(time.time() - t)    
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)



@asyncio.coroutine
def init(loop):
    # 往 web对象中加入消息循环，生成一个支持异步IO的对象
    yield from orm.create_pool(loop=loop, **configs.db)
    app = web.Application(loop=loop, middlewares=[
        logger_factory, auth_factory, response_factory
    ])    
    # filters : {'datetime': <function datetime_filter at 0x0000000002062EA0>}
    init_jinja2(app, filters=dict(datetime=datetime_filter))

    # handlers 为URL处理函数(handlers.py)
    add_routes(app, 'handlers')

    add_static(app)
    # 监听127.0.0.1:9000 端口的http请求
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000...')
    # 把监听http请求的这个协程返回给loop - 用以持续监听http请求
    return srv

# 创建一个事件循环
loop = asyncio.get_event_loop()
# 协程注册到事件循环，并启动事件循环
loop.run_until_complete(init(loop))
loop.run_forever()
