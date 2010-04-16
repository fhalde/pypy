import sys

from pypy.interpreter.baseobjspace import W_Root, Wrappable, SpaceCache
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.module.cpyext.api import cpython_api, bootstrap_function, \
     PyObject, ADDR,\
     Py_TPFLAGS_HEAPTYPE, PyTypeObjectPtr
from pypy.module.cpyext.state import State
from pypy.objspace.std.typeobject import W_TypeObject
from pypy.objspace.std.objectobject import W_ObjectObject
from pypy.rlib.objectmodel import specialize, we_are_translated
from pypy.rpython.annlowlevel import llhelper

#________________________________________________________
# type description

class BaseCpyTypedescr(object):
    pass

typedescr_cache = {}

def make_typedescr(typedef, **kw):
    """NOT_RPYTHON

    basestruct: The basic structure to allocate
    alloc     : allocate and basic initialization of a raw PyObject
    attach    : Function called to tie a raw structure to a pypy object
    realize   : Function called to create a pypy object from a raw struct
    dealloc   : a cpython_api(external=False), similar to PyObject_dealloc
    """

    tp_basestruct = kw.get('basestruct', PyObject.TO)
    tp_alloc      = kw.get('alloc')
    tp_attach     = kw.get('attach')
    tp_realize    = kw.get('realize')
    tp_dealloc    = kw.get('dealloc')

    null_dealloc = lltype.nullptr(lltype.FuncType([PyObject], lltype.Void))

    class CpyTypedescr(BaseCpyTypedescr):
        basestruct = tp_basestruct
        realize = tp_realize

        def get_dealloc(self, space):
            if tp_dealloc:
                return llhelper(
                    tp_dealloc.api_func.functype,
                    tp_dealloc.api_func.get_wrapper(space))
            else:
                from pypy.module.cpyext.typeobject import subtype_dealloc
                return llhelper(
                    subtype_dealloc.api_func.functype,
                    subtype_dealloc.api_func.get_wrapper(space))

        if tp_alloc:
            def allocate(self, space, w_type):
                return tp_alloc(space, w_type)
        else:
            def allocate(self, space, w_type):
                # similar to PyType_GenericAlloc?
                # except that it's not related to any pypy object.
                obj = lltype.malloc(tp_basestruct, flavor='raw', zero=True)
                pyobj = rffi.cast(PyObject, obj)
                pyobj.c_ob_refcnt = 1
                pyobj.c_ob_type = rffi.cast(PyTypeObjectPtr, make_ref(space, w_type))
                return pyobj

        if tp_attach:
            def attach(self, space, pyobj, w_obj):
                tp_attach(space, pyobj, w_obj)
        else:
            def attach(self, space, pyobj, w_obj):
                pass

        if tp_realize:
            def realize(self, space, ref):
                return tp_realize(space, ref)
        else:
            def realize(self, space, ref):
                raise TypeError("cannot realize")
    if typedef:
        CpyTypedescr.__name__ = "CpyTypedescr_%s" % (typedef.name,)

    typedescr_cache[typedef] = CpyTypedescr()

@bootstrap_function
def init_pyobject(space):
    from pypy.module.cpyext.object import PyObject_dealloc
    # typedescr for the 'object' type
    make_typedescr(space.w_object.instancetypedef,
                   dealloc=PyObject_dealloc)
    # almost all types, which should better inherit from object.
    make_typedescr(None)

@specialize.memo()
def _get_typedescr_1(typedef):
    try:
        return typedescr_cache[typedef]
    except KeyError:
        if typedef.base is not None:
            return _get_typedescr_1(typedef.base)
        return typedescr_cache[None]

def get_typedescr(typedef):
    if typedef is None:
        return typedescr_cache[None]
    else:
        return _get_typedescr_1(typedef)

#________________________________________________________
# refcounted object support

class NullPointerException(Exception):
    pass

class InvalidPointerException(Exception):
    pass

DEBUG_REFCOUNT = False

def debug_refcount(*args, **kwargs):
    frame_stackdepth = kwargs.pop("frame_stackdepth", 2)
    assert not kwargs
    frame = sys._getframe(frame_stackdepth)
    print >>sys.stderr, "%25s" % (frame.f_code.co_name, ),
    for arg in args:
        print >>sys.stderr, arg,
    print >>sys.stderr

def create_ref(space, w_obj, items=0):
    from pypy.module.cpyext.typeobject import W_PyCTypeObject, PyOLifeline
    from pypy.module.cpyext.pycobject import W_PyCObject, PyCObject
    w_type = space.type(w_obj)
    typedescr = get_typedescr(w_obj.typedef)

    if isinstance(w_type, W_PyCTypeObject):
        lifeline = w_obj.get_pyolifeline()
        if lifeline is not None: # make old PyObject ready for use in C code
            py_obj = lifeline.pyo
            assert py_obj.c_ob_refcnt == 0
            Py_IncRef(space, py_obj)
        else:
            w_type_pyo = make_ref(space, w_type)
            pto = rffi.cast(PyTypeObjectPtr, w_type_pyo)
            # Don't increase refcount for non-heaptypes
            if not rffi.cast(lltype.Signed, pto.c_tp_flags) & Py_TPFLAGS_HEAPTYPE:
                Py_DecRef(space, w_type_pyo)
            basicsize = pto.c_tp_basicsize + items * pto.c_tp_itemsize
            py_obj_pad = lltype.malloc(rffi.VOIDP.TO, basicsize,
                    flavor="raw", zero=True)
            py_obj = rffi.cast(PyObject, py_obj_pad)
            py_obj.c_ob_refcnt = 1
            py_obj.c_ob_type = pto
            w_obj.set_pyolifeline(PyOLifeline(space, py_obj))
    else:
        py_obj = get_typedescr(w_obj.typedef).allocate(space, w_type)
        typedescr.attach(space, py_obj, w_obj)
    return py_obj

def track_reference(space, py_obj, w_obj, borrowed=False):
    # XXX looks like a PyObject_GC_TRACK
    ptr = rffi.cast(ADDR, py_obj)
    if DEBUG_REFCOUNT:
        debug_refcount("MAKREF", py_obj, w_obj)
    state = space.fromcache(State)
    state.py_objects_w2r[w_obj] = py_obj
    state.py_objects_r2w[ptr] = w_obj
    if borrowed and ptr not in state.borrowed_objects:
        state.borrowed_objects[ptr] = None

def make_ref(space, w_obj, borrowed=False, steal=False, items=0):
    if w_obj is None:
        return lltype.nullptr(PyObject.TO)
    assert isinstance(w_obj, W_Root)
    state = space.fromcache(State)
    try:
        py_obj = state.py_objects_w2r[w_obj]
    except KeyError:
        assert not steal
        py_obj = create_ref(space, w_obj, items)
        track_reference(space, py_obj, w_obj, borrowed=borrowed)
        return py_obj

    if not steal:
        if borrowed:
            py_obj_addr = rffi.cast(ADDR, py_obj)
            if py_obj_addr not in state.borrowed_objects:
                Py_IncRef(space, py_obj)
                state.borrowed_objects[py_obj_addr] = None
        else:
            Py_IncRef(space, py_obj)
    return py_obj


def from_ref(space, ref, recurse=False):
    from pypy.module.cpyext.typeobject import PyPyType_Ready
    assert lltype.typeOf(ref) == PyObject
    if not ref:
        return None
    state = space.fromcache(State)
    ptr = rffi.cast(ADDR, ref)
    try:
        w_obj = state.py_objects_r2w[ptr]
    except KeyError:
        if recurse:
            raise InvalidPointerException(str(ref))
        ref_type = rffi.cast(PyObject, ref.c_ob_type)
        if ref != ref_type:
            w_type = from_ref(space, ref_type, True)
            assert isinstance(w_type, W_TypeObject)
            if space.is_w(w_type, space.w_str):
                return get_typedescr(w_type.instancetypedef).realize(space, ref)
            elif space.is_w(w_type, space.w_type):
                PyPyType_Ready(space, rffi.cast(PyTypeObjectPtr, ref), None)
                return from_ref(space, ref, True)
            else:
                raise InvalidPointerException(str(ref))
        else:
            raise InvalidPointerException("This should never happen")
    return w_obj


# XXX Optimize these functions and put them into macro definitions
@cpython_api([PyObject], lltype.Void)
def Py_DecRef(space, obj):
    if not obj:
        return
    assert lltype.typeOf(obj) == PyObject

    from pypy.module.cpyext.typeobject import W_PyCTypeObject
    obj.c_ob_refcnt -= 1
    if DEBUG_REFCOUNT:
        debug_refcount("DECREF", obj, obj.c_ob_refcnt, frame_stackdepth=3)
    if obj.c_ob_refcnt == 0:
        state = space.fromcache(State)
        ptr = rffi.cast(ADDR, obj)
        try:
            del state.borrowed_objects[ptr]
        except KeyError:
            pass
        if ptr not in state.py_objects_r2w:
            w_type = from_ref(space, rffi.cast(PyObject, obj.c_ob_type))
            if space.is_w(w_type, space.w_str) or space.is_w(w_type, space.w_unicode):
                # this is a half-allocated string, lets call the deallocator
                # without modifying the r2w/w2r dicts
                _Py_Dealloc(space, obj)
        else:
            w_obj = state.py_objects_r2w[ptr]
            del state.py_objects_r2w[ptr]
            w_type = space.type(w_obj)
            w_typetype = space.type(w_type)
            if not space.is_w(w_typetype, space.gettypeobject(W_PyCTypeObject.typedef)):
                _Py_Dealloc(space, obj)
            del state.py_objects_w2r[w_obj]
        if ptr in state.borrow_mapping: # move to lifeline __del__
            for containee in state.borrow_mapping[ptr]:
                w_containee = state.py_objects_r2w.get(containee, None)
                if w_containee is not None:
                    containee = state.py_objects_w2r[w_containee]
                    Py_DecRef(space, w_containee)
                    containee_ptr = rffi.cast(ADDR, containee)
                    try:
                        del state.borrowed_objects[containee_ptr]
                    except KeyError:
                        pass
                else:
                    if DEBUG_REFCOUNT:
                        print >>sys.stderr, "Borrowed object is already gone:", \
                                hex(containee)
            del state.borrow_mapping[ptr]
    else:
        if not we_are_translated() and obj.c_ob_refcnt < 0:
            print >>sys.stderr, "Negative refcount for obj %s with type %s" % (obj, rffi.charp2str(obj.c_ob_type.c_tp_name))
            assert False

@cpython_api([PyObject], lltype.Void)
def Py_IncRef(space, obj):
    if not obj:
        return
    obj.c_ob_refcnt += 1
    assert obj.c_ob_refcnt > 0
    if DEBUG_REFCOUNT:
        debug_refcount("INCREF", obj, obj.c_ob_refcnt, frame_stackdepth=3)

def _Py_Dealloc(space, obj):
    from pypy.module.cpyext.api import generic_cpy_call_dont_decref
    pto = obj.c_ob_type
    #print >>sys.stderr, "Calling dealloc slot", pto.c_tp_dealloc, "of", obj, \
    #      "'s type which is", rffi.charp2str(pto.c_tp_name)
    generic_cpy_call_dont_decref(space, pto.c_tp_dealloc, obj)

#___________________________________________________________
# Support for borrowed references

@cpython_api([PyObject], lltype.Void, external=False)
def register_container(space, container):
    state = space.fromcache(State)
    if not container: # self-managed
        container_ptr = -1
    else:
        container_ptr = rffi.cast(ADDR, container)
    assert not state.last_container, "Last container was not fetched"
    state.last_container = container_ptr

def add_borrowed_object(space, obj):
    state = space.fromcache(State)
    container_ptr = state.last_container
    state.last_container = 0
    if not container_ptr:
        raise NullPointerException
    if container_ptr == -1:
        return
    borrowees = state.borrow_mapping.get(container_ptr, None)
    if borrowees is None:
        state.borrow_mapping[container_ptr] = borrowees = {}
    obj_ptr = rffi.cast(ADDR, obj)
    borrowees[obj_ptr] = None


