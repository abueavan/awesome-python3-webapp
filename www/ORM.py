#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#orm 即将一个数据库表映射成一个类,
#简单说就是将与数据库的多种交互操作封装成一个类,
#类里面包含之前的增删查改等操作方法。

__author__ = 'abueavan'

import asyncio,logging

import aiomysql

def log(sql,args=()):
	logging.info('SQL: %s' %sql)

#创建一个全局的连接池，每个HTTP请求都可以从连接池中直接获取数据库连接
#使用连接池的好处是不必频繁地打开和关闭数据库连接，而是能复用就尽量复用
async def create_pool(loop,**kw):
	logging.info('cerate database connection pool...')
	global __pool
	__pool = await aiomysql.create_pool(
		#kw.get(key,default):通过key在kw中查找对应的value,如果没有则返回默认值default
		host=kw.get('host','localhost'),
		port=kw.get('port',3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf-8'),
        autocommit=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
		)

#关闭连接池
async def destory_pool():
	global __pool
	if __pool is not None:
		__pool.close
	await __pool.await_closed()

#Package SELECT function that can execute SELECT command.
#Setup 1:acquire connection from connection pool.
#Setup 2:create a cursor to execute MySQL command.
#Setup 3:execute MySQL command with cursor.
#Setup 4:return query result.
#协程:面向sql的查询操作:size指定返回的查询结果数
async def select(sql, args, size=None):
	log(sql,args)
	global __pool
	async with __pool.acquire() as conn:
		 #查询需要返回查询的结果,按照dict返回,所以游标cursor中传入了参数aiomysql.DictCursor
		async with conn.cursor(aiomysql.DictCursor) as cur:
			#执行sql语句前,先将sql语句中的占位符?换成mysql中采用的占位符%s 
			await cur.execute(sql.replace('?','%s'),args or ())
			if size:
				rs = await cur.fetchmany(size)
			else:
				rs = await cur.fetchall()
			logging.info('row returned: %s' % len(rs))
			return rs

 #Package execute function that can execute INSERT,UPDATE and DELETE command
async def execute(sql,args,autocommit=True):
 	log(sql)
 	async with __pool.acquire() as conn:
 		if not autocommit:
 			#如果MySQL禁止隐式提交，则标记事务开始
 			await conn.begin()
 		try:
 			async with conn.cursor(aiomysql.DictCursor) as cur:
 				#同理,execute操作只返回行数,故不需要dict 
 				await cur.execute(sql.replace('?','%s'),args)
 				affected = cur.rowcount
 			if not autocommit:
 				#如果MySQL禁止隐式提交，手动提交事务
 				await conn.commit()
 		except BaseException as e:
 			 #如果事务处理出现错误，则回退
 			if not autocommit:
 				await conn.rollback()
 			raise
 		return affected

#Create placeholder with '?'
#查询字段计数:替换成sql识别的'?'
#根据输入的字段生成占位符列表
def create_args_string(num):
	L = []
	for i in range(num):
		L.append('?')
	#用,将占位符?拼接起来 
	return ','.join(L)

#A base class about Field
#定义Field类,保存数据库中表的字段名和字段类型
#描述字段的字段名，数据类型，键信息，默认值
class Field(object):

	#表的字段包括:名字、类型、是否为主键、默认值
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    #打印数据库中的表时,输出表的信息:类名、字段类型、字段名
    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

#定义不同类型的衍生Field
#表的不同列的字段的类型不同
class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
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

#Meatclass about ORM
#定义Model的metaclass元类
#所有的元类都继承自type
#ModelMetaclass元类定义了所有Model基类(继承ModelMetaclass)的子类实现的操作
# -*-ModelMetaclass:为一个数据库表映射成一个封装的类做准备
#作用
#首先，拦截类的创建,
#创造类的时候,排除对Model类的修改;
#然后，修改类
#最后，返回修改后的类
class ModelMetaclass(type):

	#__new__控制__init__的执行,所以在其执行之前 
    #cls:代表要__init__的类,此参数在实例化时由python解释器自动提供(eg:下文的User、Model) 
    #bases:代表继承父类的集合 
    #attrs:类的方法集合，attrs是即将要创建的class的“属性”，attrs['add']相当于下面的def add(self, value)；
    #可以把类看成是metaclass创建出来的“实例” 
    #采集应用元类的子类属性信息
    #将采集的信息作为参数传入__new__方法     
    #应用__new__方法修改类
    def __new__(cls, name, bases, attrs):
    	#不对Model类应用元类
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)
         #获取数据库表名。若__table__为None,则取用类名
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))

        #存储映射表类的属性（键-值）
        mappings = dict()
        #存储映射表类的非主键属性(仅键）
        fields = []
        #主键对应字段
        primaryKey = None
        #k:当前类的属性(字段名);v：继承自Field的不同字段类（的方法）
        #在当前类中查找所有的类属性(attrs),如果找到Field属性,就保存在__mappings__的dict里
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v

                if v.primary_key:
                    # 找到主键:
                    logging.info('Found primary key')
                    #主键只有一个,不能多次赋值
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                	#非主键,一律放在fields
                    fields.append(k)

        #如果没有主键抛出异常
        if not primaryKey:
            raise StandardError('Primary key not found.')

        #删除映射表类的属性，以便应用新的属性
        for k in mappings.keys():
            attrs.pop(k)

        #使用反单引号" ` "区别MySQL保留字，提高兼容性
        #保存非主键属性为字符串列表形式
        #将非主键属性变成`id`,`name`这种形式(带反引号) 
        #repr函数和反引号:取得对象的规范字符串表示 
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))

        #重写属性
        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名
        #构造默认的增删改查语句 
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        
        #返回修改后的类
        return type.__new__(cls, name, bases, attrs)

#定义ORM所有映射的基类:Model
#Model类的任意子类可以映射一个数据库表
#Model类可以看做是对所有数据库表操作的基本定义的映射
#基于字典查询形式
#Model从dict继承,拥有字典的所有功能,同时实现特殊方法__getattr__和__setattr__,能够实现属性操作
#实现数据库操作的所有方法,定义为class方法,所有继承自Model都具有数据库操作方法
#A base class about Model
#继承dict类特性
#附加方法：
#       以属性形式获取值
#       拦截私设属性
class Model(dict, metaclass=ModelMetaclass):

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
    	#内建函数getattr会自动处理
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

    #ORM框架下，每条记录作为对象返回
	#申明是类方法:有类变量cls传入,cls可以做一些相关的处理 
	#有子类继承时,调用该方法,传入的类变量cls是子类,而非父类 
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]
        #添加WHERE子句
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        #添加ORDER BY子句
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        #添加LIMIT子句
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
        #execute SQL
        #返回的rs是一个元素是tuple的list 
        rs = await select(' '.join(sql), args)
        #**r 是关键字参数,构成了一个cls类的列表,其实就是每一条记录对应的类实例
        return [cls(**r) for r in rs]

    #过滤结果数量
    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    #返回主键的一条记录
    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    #INSERT command
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    #UPDATE command
    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    #DELETE command
    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)