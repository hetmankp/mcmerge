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
        
