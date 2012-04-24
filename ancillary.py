import itertools

class Enum(type):
    """ Very simple enumeration """
    
    class EnumElement(object):
        def __init__(self, name, val=None):
            self.__val = val
            self.__name = name
            
        def __cmp__(self, other):
            return cmp(self.val, other.val)
        
        def __eq__(self, other):
            if isinstance(other, basestring):
                return self.__name == other
            else:
                return object.__eq__(self, other)
            
        def __str__(self):
            return self.__name
    
    def __new__(mcs, name, bases, dct):
        ElementClass = type(name+'Element', (mcs.EnumElement,), {})
        
        elements = []
        for i, elt in enumerate(dct.pop('__elements__')):
            if elt in dct:
                raise KeyError('must be unique')
            else:
                elements.append(ElementClass(elt, i))
                dct[elt] = elements[-1]
                
        dct['_%s__elements' % mcs.__name__] = elements
        
        return type.__new__(mcs, name, bases, dct)
    
    def __iter__(cls):
        def gen():
            for e in cls.__elements:
                yield e
                
        return gen()
    
    def __contains__(cls, item):
        return item in cls.__elements

def record(name, elements):
    """
    Like collections.namedtuple but with mutable elements. Only
    accepts positional parameters.
    """
    
    def __init__(self, *args):
        if len(args) != len(self.__slots__):
            raise TypeError('__init__() takes exactly %d arguments (%d given)' % (len(self.__slots__), len(args)))
        for name, arg in itertools.izip(self.__slots__, args):
            setattr(self, name, arg)
            
    def __repr__(self):
        return '%s(%s)' % (
            self.__class__.__name__,
            ', '.join(('%s=%s' % (name, repr(getattr(self, name)))) for name in self.__slots__)
        )
        
    return type(name, (object,), dict(__slots__=list(elements), __init__=__init__, __repr__=__repr__))

def namedrecord(name, elements):
    """
    Like collections.namedtuple but with mutable elements. Accepts
    keyword parameters but instantiation is slower than record.
    """
    
    def __init__(self, *args, **kwargs):
        if len(args) > len(self.__slots__):
            raise TypeError("__init__() takes exactly %d arguments (%d given)" % (len(self.__slots__) + 1, len(args) + 1))
        
        params = {}
        for name, val in itertools.izip(self.__slots__, args):
            params[name] = arg
            
        slots = set(__slots__)
        for name, val in kwargs.iteritems():
            if name not in slots:
                raise TypeError("__init__() got an unexpected keyword argument '%s'" % name)
            elif name in params:
                raise TypeError("__init__() got multiple values for keyword argument '%s'" % name)
            else:
                params[name] = val
            
        if len(params) != len(self.__slots__):
            raise TypeError("__init__() takes exactly %d arguments (%d given)" % (len(self.__slots__) + 1, len(params) + 1))
        
        for name, arg in itertools.izip(self.__slots__, args):
            setattr(self, name, arg)
            
    def __repr__(self):
        return '%s(%s)' % (
            self.__class__.__name__,
            ', '.join(('%s=%s' % (name, repr(getattr(self, name)))) for name in self.__slots__)
        )
        
    return type(name, (object,), dict(__slots__=list(elements), __init__=__init__, __repr__=__repr__))

def extend(iterable, n=None):
    """
    Extends an iterable by repeating the last value up to
    n times (or indefinitely if not given.
    """
    
    itr = iter(iterable)
    while True:
        try:
            val = itr.next()
            yield val
        except StopIteration:
            break
    
    try:
        if n is None:
            tail = itertools.repeat(val)
        else:
            tail = itertools.repeat(val, n)
    except NameError:
        raise StopIteration
    
    for x in tail:
        yield x
        
