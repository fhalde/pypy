from pypy.interpreter.error import OperationError
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.rlib.rarithmetic import r_singlefloat
from pypy.objspace.std.intobject import W_IntObject

from pypy.module.cppyy import helper, capi

_converters = {}

class TypeConverter(object):
    def _get_fieldptr(self, space, w_obj, offset):
        obj = space.interpclass_w(space.findattr(w_obj, space.wrap("_cppinstance")))
        return lltype.direct_ptradd(obj.rawobject, offset)

    def _is_abstract(self):
        raise NotImplementedError(
            "abstract base class (actual: %s)" % type(self).__name__)

    def convert_argument(self, space, w_obj):
        self._is_abstract()

    def from_memory(self, space, w_obj, offset):
        self._is_abstract()

    def to_memory(self, space, w_obj, w_value, offset):
        self._is_abstract()

    def free_argument(self, arg):
        lltype.free(arg, flavor='raw')


class VoidConverter(TypeConverter):
    def __init__(self, space, name):
        self.name = name

    def convert_argument(self, space, w_obj):
        raise OperationError(space.w_TypeError,
                             space.wrap('no converter available for type "%s"' % self.name))


class BoolConverter(TypeConverter):
    def convert_argument(self, space, w_obj):
        arg = space.c_int_w(w_obj)
        if arg != False and arg != True:
            raise OperationError(space.w_TypeError,
                                 space.wrap("boolean value should be bool, or integer 1 or 0"))
        x = lltype.malloc(rffi.LONGP.TO, 1, flavor='raw')
        x[0] = arg
        return rffi.cast(rffi.VOIDP, x)

class CharConverter(TypeConverter):
    def _from_space(self, space, w_value):
        # allow int to pass to char and make sure that str is of length 1
        if type(w_value) == W_IntObject:
            try:
                value = chr(space.c_int_w(w_value))     
            except ValueError, e:
                raise OperationError(space.w_TypeError, space.wrap(str(e)))
        else:
            value = space.str_w(w_value)

        if len(value) != 1:  
            raise OperationError(space.w_TypeError,
                                 space.wrap("char expecter, got string of size %d" % len(value)))
        return value

    def convert_argument(self, space, w_obj):
        arg = self._from_space(space, w_obj)
        x = rffi.str2charp(arg)
        return rffi.cast(rffi.VOIDP, x)

    def from_memory(self, space, w_obj, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        return space.wrap(fieldptr[0])

    def to_memory(self, space, w_obj, w_value, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        fieldptr[0] = self._from_space(space, w_value)

class LongConverter(TypeConverter):
    def convert_argument(self, space, w_obj):
        arg = space.c_int_w(w_obj)
        x = lltype.malloc(rffi.LONGP.TO, 1, flavor='raw')
        x[0] = arg
        return rffi.cast(rffi.VOIDP, x)

    def from_memory(self, space, w_obj, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        longptr = rffi.cast(rffi.LONGP, fieldptr)
        return space.wrap(longptr[0])

    def to_memory(self, space, w_obj, w_value, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        longptr = rffi.cast(rffi.LONGP, fieldptr)
        longptr[0] = space.c_int_w(w_value)

class ShortConverter(LongConverter):
    def from_memory(self, space, w_obj, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        intptr = rffi.cast(rffi.SHORTP, fieldptr)
        return space.wrap(intptr[0])

    def to_memory(self, space, w_obj, w_value, offset):
        import struct
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        pack = struct.pack('h', space.unwrap(w_value))         # unchecked
        fieldptr[0] = pack[0]
        fieldptr[1] = pack[1]

class FloatConverter(TypeConverter):
    def convert_argument(self, space, w_obj):
        arg = space.float_w(w_obj)
        x = lltype.malloc(rffi.FLOATP.TO, 1, flavor='raw')
        x[0] = r_singlefloat(arg)
        return rffi.cast(rffi.VOIDP, x)        

    def from_memory(self, space, w_obj, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        floatptr = rffi.cast(rffi.FLOATP, fieldptr)
        return space.wrap(float(floatptr[0]))

    def to_memory(self, space, w_obj, w_value, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        floatptr = rffi.cast(rffi.FLOATP, fieldptr)
        floatptr[0] = r_singlefloat(space.float_w(w_value))

class DoubleConverter(TypeConverter):
    def convert_argument(self, space, w_obj):
        arg = space.float_w(w_obj)
        x = lltype.malloc(rffi.DOUBLEP.TO, 1, flavor='raw')
        x[0] = arg
        return rffi.cast(rffi.VOIDP, x)        

    def from_memory(self, space, w_obj, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        doubleptr = rffi.cast(rffi.DOUBLEP, fieldptr)
        return space.wrap(doubleptr[0])

    def to_memory(self, space, w_obj, w_value, offset):
        fieldptr = self._get_fieldptr(space, w_obj, offset)
        doubleptr = rffi.cast(rffi.DOUBLEP, fieldptr)
        doubleptr[0] = space.float_w(w_value)


class CStringConverter(TypeConverter):
    def convert_argument(self, space, w_obj):
        arg = space.str_w(w_obj)
        x = rffi.str2charp(arg)
        return rffi.cast(rffi.VOIDP, x)


class InstancePtrConverter(TypeConverter):
    _immutable_ = True
    def __init__(self, space, cpptype):
        self.cpptype = cpptype

    def convert_argument(self, space, w_obj):
        from pypy.module.cppyy import interp_cppyy
        w_cppinstance = space.findattr(w_obj, space.wrap("_cppinstance"))
        if w_cppinstance is not None:
            w_obj = w_cppinstance
        obj = space.interpclass_w(w_obj)
        if isinstance(obj, interp_cppyy.W_CPPInstance):
            if capi.c_is_subtype(obj.cppclass.handle, self.cpptype.handle):
                return obj.rawobject
        raise OperationError(space.w_TypeError,
                             space.wrap("cannot pass %s as %s" % (
                                 space.type(w_obj).getname(space, "?"),
                                 self.cpptype.name)))

    def free_argument(self, arg):
        pass
        

def get_converter(space, name):
    from pypy.module.cppyy import interp_cppyy
    # The matching of the name to a converter should follow:
    #   1) full, exact match
    #   2) match of decorated, unqualified type
    #   3) accept const ref as by value
    #   4) accept ref as pointer
    #   5) generalized cases (covers basically all user classes)
    #   6) void converter, which fails on use

    try:
        return _converters[name]
    except KeyError:
        pass

    compound = helper.compound(name)
    cpptype = interp_cppyy.type_byname(space, helper.clean_type(name))
    if compound == "*":
        return InstancePtrConverter(space, cpptype)

    # return a void converter here, so that the class can be build even
    # when some types are unknown; this overload will simply fail on use
    return VoidConverter(space, name)


_converters["bool"]                = BoolConverter()
_converters["char"]                = CharConverter()
_converters["unsigned char"]       = CharConverter()
_converters["short int"]           = ShortConverter()
_converters["unsigned short int"]  = ShortConverter()
_converters["int"]                 = LongConverter()
_converters["unsigned int"]        = LongConverter()
_converters["long int"]            = LongConverter()
_converters["unsigned long int"]   = LongConverter()
_converters["float"]               = FloatConverter()
_converters["double"]              = DoubleConverter()
_converters["const char*"]         = CStringConverter()
