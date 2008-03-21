from pypy.annotation import model as annmodel
from pypy.tool.pairtype import pair, pairtype
from pypy.jit.hintannotator.bookkeeper import getbookkeeper
from pypy.rpython.lltypesystem import lltype, lloperation
from pypy.rpython.ootypesystem import ootype
from pypy.translator.simplify import get_funcobj, get_functype

UNARY_OPERATIONS = """same_as hint getfield setfield getsubstruct getarraysize
                      getinteriorfield getinteriorarraysize setinteriorfield
                      cast_pointer
                      direct_call
                      indirect_call
                      int_is_true int_neg int_abs int_invert bool_not
                      int_neg_ovf int_abs_ovf
                      uint_is_true
                      cast_int_to_char
                      cast_int_to_uint
                      cast_uint_to_int
                      cast_char_to_int
                      cast_bool_to_int
                      cast_ptr_to_int
                      ptr_nonzero
                      ptr_iszero
                      is_early_constant
                      jit_merge_point
                      can_enter_jit
                      oogetfield
                      oosetfield
                      oononnull
                      ooupcast
                      oodowncast
                      oois
                      subclassof
                      instanceof
                      oostring
                      """.split()

BINARY_OPERATIONS = """int_add int_sub int_mul int_mod int_and int_rshift
                       int_lshift int_floordiv int_xor int_or
                       int_add_ovf int_sub_ovf int_mul_ovf int_mod_ovf
                       int_floordiv_ovf int_lshift_ovf int_add_nonneg_ovf
                       uint_add uint_sub uint_mul uint_mod uint_and
                       uint_lshift uint_rshift uint_floordiv
                       char_gt char_lt char_le char_ge char_eq char_ne
                       int_gt int_lt int_le int_ge int_eq int_ne
                       uint_gt uint_lt uint_le uint_ge uint_eq uint_ne 
                       getarrayitem setarrayitem
                       getarraysubstruct
                       ptr_eq ptr_ne""".split()

class HintError(Exception):
    pass

class OriginFlags(object):
    fixed = False
    read_positions = None
    greenargs = False

    def __init__(self, bookkeeper=None, spaceop=None):
        self.bookkeeper = bookkeeper
        self.spaceop = spaceop

    def __repr__(self):
        return '<%s %s>' % (getattr(self.spaceop, 'result', '?'),
                            self.reprstate())

    def reprstate(self):
        if self.fixed:
            s = "fixed "
        elif self.greenargs:
            s = "green"
        else:
            s = ""
        return "%sorigin" % (s,)

    def read_fixed(self):
        if self.read_positions is None:
            self.read_positions = {}
        self.read_positions[getbookkeeper().position_key] = True
        return self.fixed

    def set_fixed(self):
        if not self.fixed:
            self.fixed = True
            if self.read_positions:
                annotator = getbookkeeper().annotator
                for p in self.read_positions:
                    annotator.reflowfromposition(p)

    def record_dependencies(self, greenorigindependencies,
                                  callreturndependencies):
        deps = greenorigindependencies.setdefault(self, [])
        deps.extend(self.spaceop.args)


class CallOpOriginFlags(OriginFlags):

    def record_dependencies(self, greenorigindependencies,
                                  callreturndependencies):
        bk = self.bookkeeper
        if self.spaceop.opname in ('direct_call', 'ts_metacall'):
            args = self.spaceop.args[1:]
        elif self.spaceop.opname == 'indirect_call':
            args = self.spaceop.args[1:-1]
            # indirect_call with a red callable must return a red
            # (see test_indirect_yellow_call)
            v_callable = self.spaceop.args[0]
            retdeps = greenorigindependencies.setdefault(self, [])
            retdeps.append(v_callable)
        elif self.spaceop.opname == 'oosend':
            args = self.spaceop.args[1:]
            methname = self.spaceop.args[0].value
            TYPE = self.spaceop.args[1].concretetype
            graphs = TYPE._lookup_graphs(methname)
            if len(graphs) > 1:
                v_self = self.spaceop.args[1]
                retdeps = greenorigindependencies.setdefault(self, [])
                retdeps.append(v_self)
        else:
            raise AssertionError(self.spaceop.opname)

        graph = self.any_called_graph
        call_families = bk.tsgraph_maximal_call_families
        _, repgraph, callfamily = call_families.find(graph)

        # record the argument and return value dependencies
        retdeps = callreturndependencies.setdefault(self, [])
        for graph in callfamily.tsgraphs:
            retdeps.append(graph)
            for i, v in enumerate(args):
                argorigin = bk.myinputargorigin(graph, i)
                deps = greenorigindependencies.setdefault(argorigin, [])
                deps.append(v)


class InputArgOriginFlags(OriginFlags):

    def __init__(self, bookkeeper, graph, i):
        OriginFlags.__init__(self, bookkeeper)
        self.graph = graph
        self.i = i

    def getarg(self):
        return self.graph.getargs()[self.i]

    def __repr__(self):
        return '<%s %s>' % (self.getarg(), self.reprstate())

    def record_dependencies(self, greenorigindependencies,
                                  callreturndependencies):
        bk = self.bookkeeper
        call_families = bk.tsgraph_maximal_call_families
        _, repgraph, callfamily = call_families.find(self.graph)

        # record the fact that each graph's input args should be as red
        # as each other's
        if self.graph is repgraph:
            deps = greenorigindependencies.setdefault(self, [])
            v = self.getarg()
            for othergraph in callfamily.tsgraphs:
                if othergraph is not repgraph:
                    deps.append(othergraph.getargs()[self.i])
                    otherorigin = bk.myinputargorigin(othergraph, self.i)
                    otherdeps = greenorigindependencies.setdefault(otherorigin,
                                                                   [])
                    otherdeps.append(v)

# ____________________________________________________________


class SomeLLAbstractValue(annmodel.SomeObject):

    def __init__(self, T, deepfrozen=False):
        self.concretetype = T
        assert self.__class__ != SomeLLAbstractValue
        self.deepfrozen = deepfrozen

    def is_green(self):
        return False

    def clone(self):
        c = object.__new__(self.__class__)
        c.__dict__.update(self.__dict__)
        return c

class SomeLLAbstractConstant(SomeLLAbstractValue):
    " color: dont know yet.. "

    def __init__(self, T, origins, eager_concrete=False, myorigin=None,
                 deepfrozen=False):
        SomeLLAbstractValue.__init__(self, T, deepfrozen)
        self.origins = origins
        self.eager_concrete = eager_concrete
        self.myorigin = myorigin

    def fmt_origins(self, origins):
        counts = {}
        for o in origins:
            x = o.reprstate()
            counts[x] = counts.get(x, 0) + 1
        items = counts.items()
        items.sort()
        lst = []
        for key, count in items:
            s = ''
            if count > 1:
                s += '%d*' % count
            s += key
            lst.append(s)
        return '<%s>' % (', '.join(lst),)

    def fmt_myorigin(self, myorigin):
        if myorigin is None:
            return None
        else:
            return repr(myorigin)

    def is_fixed(self):
        for o in self.origins:
            if not o.fixed:
                return False
        return self.concretetype is not lltype.Void

    def is_green(self):
        return (self.concretetype is lltype.Void or
                self.is_fixed() or self.eager_concrete or
                (self.myorigin is not None and self.myorigin.greenargs))

    def annotationcolor(self):
        """Compute the color of the variables with this annotation
        for the pygame viewer
        """
        try:
            if self.concretetype is lltype.Void:
                return annmodel.s_ImpossibleValue.annotationcolor
            elif self.eager_concrete:
                return (0,100,0)     # green
            elif self.is_green():
                return (50,140,0)    # green-dark-cyan
            else:
                return None
        except KeyError:     # can occur in is_green() if annotation crashed
            return (0,200,200)
    annotationcolor = property(annotationcolor)


class SomeLLAbstractVariable(SomeLLAbstractValue):
    " color: hopelessly red"

    def __init__(self, T, deepfrozen=False):
        SomeLLAbstractValue.__init__(self, T, deepfrozen)
        assert T is not lltype.Void   # use bookkeeper.valueoftype()

def variableoftype(TYPE, deepfrozen=False, cause=None):
    # the union of all annotations of the given TYPE - that's a
    # SomeLLAbstractVariable, unless TYPE is Void
    if TYPE is lltype.Void:
        return s_void
    else:
        hs_res = SomeLLAbstractVariable(TYPE, deepfrozen=deepfrozen)
        if cause is not None:
            getbookkeeper().setcause(hs_res, cause)
        return hs_res


class SomeLLAbstractContainer(SomeLLAbstractValue):
    deepfrozen = False     # XXX for now

    def __init__(self, contentdef):
        self.contentdef = contentdef
        T = contentdef.T
        if isinstance(T, ootype.OOType):
            self.concretetype = T
        else:
            self.concretetype = lltype.Ptr(T)

    def annotationcolor(self):
        """Compute the color of the variables with this annotation
        for the pygame viewer
        """
        if getattr(self.contentdef, 'degenerated', False):
            return None
        else:
            return (0,60,160)  # blue
    annotationcolor = property(annotationcolor)


s_void = SomeLLAbstractConstant(lltype.Void, {})


setunion = annmodel.setunion

def setadd(set, newitem):
    if newitem not in set:
        set = set.copy()
        set[newitem] = True
    return set

def newset(set, *sets):
    set = set.copy()
    for s2 in sets:
        set.update(s2)
    return set

def reorigin(hs_v1, *deps_hs):
    """Make a copy of hs_v1 with its origins removed and replaced by myorigin().
    Optionally, the origins of other annotations can also be added.
    """
    if isinstance(hs_v1, SomeLLAbstractConstant):
        deps_origins = [hs_dep.origins for hs_dep in deps_hs
                        if isinstance(hs_dep, SomeLLAbstractConstant)]
        d = newset({getbookkeeper().myorigin(): True},
                   *deps_origins)
        return SomeLLAbstractConstant(hs_v1.concretetype, d,
                                      eager_concrete=hs_v1.eager_concrete,
                                      deepfrozen=hs_v1.deepfrozen)
    else:
        return hs_v1

def originalconcretetype(hs):
    if isinstance(hs, annmodel.SomeImpossibleValue):
        return lltype.Void
    else:
        return hs.concretetype

def deepunfreeze(hs):
    if hs.deepfrozen:
        hs = hs.clone()
        hs.deepfrozen = False
    return hs

# ____________________________________________________________
# operations

class __extend__(SomeLLAbstractValue):

    def same_as(hs_v1):
        return hs_v1

    def hint(hs_v1, hs_flags):
        if hs_flags.const.get('variable', False): # only for testing purposes!!!
            return variableoftype(hs_v1.concretetype,
                                  cause='a hint variable=True')
        if hs_flags.const.get('forget', False):
            # turn a variable to a constant
            origin = getbookkeeper().myorigin()
            return SomeLLAbstractConstant(hs_v1.concretetype, {origin: True})
        if hs_flags.const.get('promote', False):
            hs_concrete = SomeLLAbstractConstant(hs_v1.concretetype, {})
            #hs_concrete.eager_concrete = True
            return hs_concrete 
        if hs_flags.const.get('deepfreeze', False):
            hs_clone = hs_v1.clone()
            hs_clone.deepfrozen = True
            return hs_clone
        for name in ["reverse_split_queue", "global_merge_point",
                     "access_directly"]:
            if hs_flags.const.get(name, False):
                return

        cause = getbookkeeper().getcause(hs_v1)
        if cause is None:
            causeinfo = ''
        else:
            causeinfo = '\n  caused by %s' % (cause,)
        raise HintError("hint %s makes no sense on %r%s" % (hs_flags.const,
                                                            hs_v1, causeinfo))
    def is_early_constant(hs_v1):
        return SomeLLAbstractConstant(lltype.Bool, {})

    def getfield(hs_v1, hs_fieldname):
        S = hs_v1.concretetype.TO
        FIELD_TYPE = getattr(S, hs_fieldname.const)
        return variableoftype(FIELD_TYPE, hs_v1.deepfrozen, cause=hs_v1)

    def oogetfield(hs_v1, hs_fieldname):
        _, FIELD_TYPE = hs_v1.concretetype._lookup_field(hs_fieldname.const)
        return variableoftype(FIELD_TYPE, hs_v1.deepfrozen, cause=hs_v1)

    def setfield(hs_v1, hs_fieldname, hs_value):
        pass

    def oosetfield(hs_v1, hs_fieldname, hs_value):
        pass

    def getsubstruct(hs_v1, hs_fieldname):
        S = hs_v1.concretetype.TO
        FIELD_TYPE = getattr(S, hs_fieldname.const)
        hs = SomeLLAbstractVariable(lltype.Ptr(FIELD_TYPE), hs_v1.deepfrozen)
        getbookkeeper().setcause(hs, hs_v1)
        return hs

    def _getinterior(hs_v1, *offsets_hs):
        hs_container = hs_v1
        for hs_offset in offsets_hs:
            if hs_offset.concretetype is lltype.Signed:
                hs_container = pair(hs_container,hs_offset).getarraysubstruct()
            else:
                hs_container = hs_container.getsubstruct(hs_offset)
        return hs_container

    def getinteriorfield(hs_v1, *offsets_hs):
        hs_container = hs_v1._getinterior(*offsets_hs[:-1])
        hs_lastofs   = offsets_hs[-1]
        if hs_lastofs.concretetype is lltype.Signed:
            return pair(hs_container, hs_lastofs).getarrayitem()
        else:
            return hs_container.getfield(hs_lastofs)

    def getinteriorarraysize(hs_v1, *offsets_hs):
        return hs_v1._getinterior(*offsets_hs).getarraysize()

    def setinteriorfield(hs_v1, *offsets_and_val_hs):
        hs_inner   = hs_v1._getinterior(*offsets_and_val_hs[:-2])
        hs_lastofs = offsets_and_val_hs[-2]
        hs_value   = offsets_and_val_hs[-1]
        if hs_lastofs.concretetype is lltype.Signed:
            pair(hs_inner, hs_lastofs).setarrayitem(hs_value)
        else:
            hs_inner.setfield(hs_lastofs, hs_value)

    def cast_pointer(hs_v1):
        RESTYPE = getbookkeeper().current_op_concretetype()
        hs = SomeLLAbstractVariable(RESTYPE, hs_v1.deepfrozen)
        getbookkeeper().setcause(hs, hs_v1)
        return hs

    ooupcast = cast_pointer
    oodowncast = cast_pointer

    def indirect_call(hs_v1, *args_hs):
        hs_graph_list = args_hs[-1]
        args_hs = args_hs[:-1]
        assert hs_graph_list.is_constant()
        graph_list = hs_graph_list.const
        FUNC = get_functype(hs_v1.concretetype)
        return hs_v1._call_multiple_graphs(graph_list, FUNC.RESULT, *args_hs)

    def _call_multiple_graphs(hs_v1, graph_list, RESULT, *args_hs):
        if graph_list is None:
            # cannot follow indirect calls to unknown targets
            return variableoftype(RESULT,
                                  cause='an indirect call to unknown targets')

        bookkeeper = getbookkeeper()
        myorigin = bookkeeper.myorigin()
        myorigin.__class__ = CallOpOriginFlags     # thud
        fixed = myorigin.read_fixed()
        tsgraphs_accum = []
        hs_res = bookkeeper.graph_family_call(graph_list, fixed, args_hs,
                                              tsgraphs_accum, hs_v1)
        myorigin.any_called_graph = tsgraphs_accum[0]

        if isinstance(hs_res, SomeLLAbstractConstant):
            hs_res.myorigin = myorigin

        # we need to make sure that hs_res does not become temporarily less
        # general as a result of calling another specialized version of the
        # function
        return annmodel.unionof(hs_res, bookkeeper.current_op_binding())

    def _call_single_graph(hs_f1, graph, RESULT, *args_hs):
        bookkeeper = getbookkeeper()
        if not bookkeeper.annotator.policy.look_inside_graph(graph):
            return cannot_follow_call(bookkeeper, graph, args_hs, RESULT)

        # recursive call from the entry point to itself: ignore them and
        # just hope the annotations are correct
        if (bookkeeper.getdesc(graph)._cache.get(None, None) is
            bookkeeper.annotator.translator.graphs[0]):
            return variableoftype(RESULT, cause="recursive call from the "
                                                "entry point to itself")

        myorigin = bookkeeper.myorigin()
        myorigin.__class__ = CallOpOriginFlags     # thud
        fixed = myorigin.read_fixed()
        tsgraphs_accum = []
        hs_res = bookkeeper.graph_call(graph, fixed, args_hs,
                                       tsgraphs_accum)
        myorigin.any_called_graph = tsgraphs_accum[0]

        if isinstance(hs_res, SomeLLAbstractConstant):
            hs_res.myorigin = myorigin        

        # we need to make sure that hs_res does not become temporarily less
        # general as a result of calling another specialized version of the
        # function
        return annmodel.unionof(hs_res, bookkeeper.current_op_binding())

    def oosend(hs_c1, hs_name, *args_hs): 
        TYPE = hs_c1.concretetype
        name = hs_name.const
        _, meth = TYPE._lookup(name)
        METH = lltype.typeOf(meth)
        graph_list = TYPE._lookup_graphs(name)
        if not graph_list:
            # it's a graphless method of a BuiltinADTType
            bk = getbookkeeper()
            return handle_highlevel_operation_novirtual(bk, True, name, TYPE.immutable, hs_c1, *args_hs)
        elif len(graph_list) == 1:
            # like a direct_call
            graph = graph_list.pop()
            return hs_c1._call_single_graph(graph, METH.RESULT, hs_c1, *args_hs) # prepend hs_c1 to the args
        else:
            # like an indirect_call
            return hs_c1._call_multiple_graphs(graph_list, METH.RESULT, hs_c1, *args_hs) # prepend hs_c1 to the args

    def jit_merge_point(hs_numgreens, hs_numreds, *livevars_hs):
        pass     # XXX should check colors

    def can_enter_jit(hs_numgreens, hs_numreds, *livevars_hs):
        pass     # XXX should check colors

class __extend__(SomeLLAbstractConstant):

    def same_as(hs_c1):
        # this is here to prevent setup() below from adding a different
        # version of same_as()
        return hs_c1

    def hint(hs_c1, hs_flags):
        if hs_flags.const.get('concrete', False):
            for o in hs_c1.origins:
                o.set_fixed()
            hs_concrete = reorigin(hs_c1)
            hs_concrete.eager_concrete = True
            return hs_concrete 
        if hs_flags.const.get('forget', False):
            assert isinstance(hs_c1, SomeLLAbstractConstant)
            return reorigin(hs_c1)
        return SomeLLAbstractValue.hint(hs_c1, hs_flags)

    def direct_call(hs_f1, *args_hs):
        bookkeeper = getbookkeeper()
        fnobj = get_funcobj(hs_f1.const)
        if (bookkeeper.annotator.policy.oopspec and
            hasattr(fnobj._callable, 'oopspec')):
            # try to handle the call as a high-level operation
            try:
                return handle_highlevel_operation(bookkeeper, fnobj._callable,
                                                  *args_hs)
            except NotImplementedError:
                pass

        # normal call
        if not hasattr(fnobj, 'graph'):
            raise NotImplementedError("XXX call to externals or primitives")

        return hs_f1._call_single_graph(fnobj.graph, lltype.typeOf(fnobj).RESULT, *args_hs)

    def getfield(hs_c1, hs_fieldname):
        S = hs_c1.concretetype.TO
        FIELD_TYPE = getattr(S, hs_fieldname.const)
        return hs_c1.getfield_impl(S, FIELD_TYPE)

    def oogetfield(hs_c1, hs_fieldname):
        S = hs_c1.concretetype
        _, FIELD_TYPE = S._lookup_field(hs_fieldname.const)
        return hs_c1.getfield_impl(S, FIELD_TYPE)

    def getfield_impl(hs_c1, S, FIELD_TYPE):
        if S._hints.get('immutable', False) or hs_c1.deepfrozen:
            origin = getbookkeeper().myorigin()
            d = setadd(hs_c1.origins, origin)
            return SomeLLAbstractConstant(FIELD_TYPE, d,
                                          eager_concrete=hs_c1.eager_concrete,
                                          myorigin=origin,
                                          deepfrozen=hs_c1.deepfrozen)
        else:
            return variableoftype(FIELD_TYPE,
                                  cause="getfield on non-immutable %s" % (S,))

    def getsubstruct(hs_c1, hs_fieldname):
        S = hs_c1.concretetype.TO
        SUB_TYPE = getattr(S, hs_fieldname.const)
        origin = getbookkeeper().myorigin()
        d = setadd(hs_c1.origins, origin)
        return SomeLLAbstractConstant(lltype.Ptr(SUB_TYPE), d,
                                      myorigin=origin,
                                      deepfrozen=hs_c1.deepfrozen)    

    def cast_pointer(hs_c1):
        bk = getbookkeeper()
        origin = bk.myorigin()
        d = setadd(hs_c1.origins, origin)
        RESTYPE = bk.current_op_concretetype()
        return SomeLLAbstractConstant(RESTYPE, d,
                                      eager_concrete = hs_c1.eager_concrete,
                                      myorigin = origin,
                                      deepfrozen = hs_c1.deepfrozen)

    ooupcast = cast_pointer
    oodowncast = cast_pointer

class __extend__(SomeLLAbstractContainer):

    def setfield(hs_s1, hs_fieldname, hs_value):
        hs_s1.contentdef.generalize_field(hs_fieldname.const, hs_value)

    def getfield(hs_s1, hs_fieldname):
        return hs_s1.contentdef.read_field(hs_fieldname.const)

    getsubstruct = getfield

    def setarrayitem(hs_a1, hs_index, hs_value):
        hs_a1.contentdef.generalize_item(hs_value)

    def getarraysize(hs_a1):
        origin = getbookkeeper().myorigin()
        return SomeLLAbstractConstant(lltype.Signed, {origin: True})

    def cast_pointer(hs_s1):
        TO = getbookkeeper().current_op_concretetype()
        res_vstruct =hs_s1.contentdef.cast(TO)
        return SomeLLAbstractContainer(res_vstruct)

    def ptr_nonzero(hs_s1):
        return getbookkeeper().immutablevalue(True)

    def ptr_iszero(hs_s1):
        return getbookkeeper().immutablevalue(False)


# ____________________________________________________________
# binary

class __extend__(pairtype(SomeLLAbstractValue, SomeLLAbstractValue)):

    def getarrayitem((hs_v1, hs_v2)):
        return variableoftype(hs_v1.concretetype.TO.OF, hs_v1.deepfrozen,
                              cause=hs_v1)

    def setarrayitem((hs_v1, hs_v2), hs_v3):
        pass

    def getarraysubstruct((hs_v1, hs_v2)):
        hs = SomeLLAbstractVariable(lltype.Ptr(hs_v1.concretetype.TO.OF),
                                      hs_v1.deepfrozen)
        getbookkeeper().setcause(hs, (hs_v1, hs_v2))
        return hs

    def union((hs_v1, hs_v2)):
        if hs_v1.deepfrozen != hs_v2.deepfrozen:
            hs_v1 = deepunfreeze(hs_v1)
            hs_v2 = deepunfreeze(hs_v2)
            if hs_v1 == hs_v2:
                return hs_v1
        return pair(hs_v1, hs_v2).union_frozen_equal()

    def invalid_union((hs_v1, hs_v2)):
        raise annmodel.UnionError("%s %s don't mix" % (hs_v1, hs_v2))

    union_frozen_equal = invalid_union


class __extend__(pairtype(SomeLLAbstractVariable, SomeLLAbstractConstant),
                 pairtype(SomeLLAbstractConstant, SomeLLAbstractVariable)):

    def union_frozen_equal((hs_v1, hs_v2)):
        assert hs_v1.concretetype == hs_v2.concretetype
        if (getattr(hs_v1, 'eager_concrete', False) or
            getattr(hs_v2, 'eager_concrete', False)):
            pair(hs_v1, hs_v2).invalid_union()
        hs_res = variableoftype(hs_v1.concretetype, hs_v1.deepfrozen)
        # we cannot use cause=... here because getbookkeeper() returns None.
        # here is a hack to try to preserve 'cause' anyway...
        if hs_res == hs_v1:
            return hs_v1
        elif hs_res == hs_v2:
            return hs_v2
        else:
            return hs_res


class __extend__(pairtype(SomeLLAbstractConstant, SomeLLAbstractConstant)):

    def union_frozen_equal((hs_c1, hs_c2)):
        assert hs_c1.concretetype == hs_c2.concretetype
        d = newset(hs_c1.origins, hs_c2.origins)
        if hs_c1.myorigin is hs_c2.myorigin:
            myorigin = hs_c1.myorigin
        else:
            myorigin = None
        return SomeLLAbstractConstant(hs_c1.concretetype, d,
                                      eager_concrete = hs_c1.eager_concrete and
                                                       hs_c2.eager_concrete,
                                      myorigin = myorigin,
                                      deepfrozen = hs_c1.deepfrozen)


    def getarrayitem((hs_c1, hs_index)):
        A = hs_c1.concretetype.TO
        READ_TYPE = A.OF
        if A._hints.get('immutable', False) or hs_c1.deepfrozen:
            origin = getbookkeeper().myorigin()
            d = newset(hs_c1.origins, hs_index.origins, {origin: True})
            return SomeLLAbstractConstant(READ_TYPE, d,
                                          eager_concrete=hs_c1.eager_concrete,
                                          myorigin=origin,
                                          deepfrozen=hs_c1.deepfrozen)
        else:
            return variableoftype(READ_TYPE,
                                  cause="getarrayitem on non-immutable %s" % A)

    def getarraysubstruct((hs_c1, hs_index)):
        A = hs_c1.concretetype.TO
        SUB_TYPE = A.OF
        origin = getbookkeeper().myorigin()
        d = newset(hs_c1.origins, hs_index.origins, {origin: True})
        return SomeLLAbstractConstant(lltype.Ptr(SUB_TYPE), d,
                                      myorigin=origin,
                                      deepfrozen=hs_c1.deepfrozen)    
        
class __extend__(pairtype(SomeLLAbstractContainer, SomeLLAbstractContainer)):

    def union_frozen_equal((hs_cont1, hs_cont2)):
        contentdef = hs_cont1.contentdef.union(hs_cont2.contentdef)
        return SomeLLAbstractContainer(contentdef)   # XXX deepfrozen?

    def ptr_eq((hs_cont1, hs_cont2)):
        return SomeLLAbstractConstant(lltype.Bool, {})

    def ptr_ne((hs_cont1, hs_cont2)):
        return SomeLLAbstractConstant(lltype.Bool, {})


class __extend__(pairtype(SomeLLAbstractContainer, SomeLLAbstractValue)):
    def union_frozen_equal((hs_cont1, hs_val2)):
        hs_cont1.contentdef.mark_degenerated()
        assert hs_cont1.concretetype == hs_val2.concretetype
        return SomeLLAbstractVariable(hs_cont1.concretetype) # XXX deepfrozen?


class __extend__(pairtype(SomeLLAbstractValue, SomeLLAbstractContainer)):
    def union_frozen_equal((hs_val1, hs_cont2)):
        return pair(hs_cont2, hs_val1).union_frozen_equal()


class __extend__(pairtype(SomeLLAbstractContainer, SomeLLAbstractValue),
                 pairtype(SomeLLAbstractValue, SomeLLAbstractContainer)):

    def ptr_eq(_):
        return getbookkeeper().immutablevalue(False)

    def ptr_ne(_):
        return getbookkeeper().immutablevalue(True)


class __extend__(pairtype(SomeLLAbstractContainer, SomeLLAbstractConstant)):

    def getarrayitem((hs_a1, hs_index)):
        hs_res = hs_a1.contentdef.read_item()
        return reorigin(hs_res, hs_res, hs_index)

# ____________________________________________________________

def handle_highlevel_operation_novirtual(bookkeeper, ismethod, name, immutable, *args_hs):
    RESULT = bookkeeper.current_op_concretetype()
    deepfrozen = ismethod and args_hs[0].deepfrozen # if self is deepfrozen, the result is it too
    if ismethod and (immutable or args_hs[0].deepfrozen):
        for hs_v in args_hs:
            if not isinstance(hs_v, SomeLLAbstractConstant):
                break
        else:
            myorigin = bookkeeper.myorigin()
            d = newset({myorigin: True}, *[hs_c.origins
                                           for hs_c in args_hs])
            return SomeLLAbstractConstant(RESULT, d,
                                          eager_concrete = False,   # probably
                                          myorigin = myorigin,
                                          deepfrozen=deepfrozen)
        cause = args_hs
    else:
        cause = "oopspec call to %s()" % name
    return variableoftype(RESULT, deepfrozen=deepfrozen, cause=cause)
    

def handle_highlevel_operation(bookkeeper, ll_func, *args_hs):
    # parse the oopspec and fill in the arguments
    operation_name, args = ll_func.oopspec.split('(', 1)
    assert args.endswith(')')
    args = args[:-1] + ','     # trailing comma to force tuple syntax
    if args.strip() == ',':
        args = '()'
    argnames = ll_func.func_code.co_varnames[:len(args_hs)]
    d = dict(zip(argnames, args_hs))
    argtuple = eval(args, d)
    args_hs = []
    for hs in argtuple:
        if not isinstance(hs, SomeLLAbstractValue):
            hs = bookkeeper.immutablevalue(hs)
        args_hs.append(hs)
    # end of rather XXX'edly hackish parsing

    if bookkeeper.annotator.policy.novirtualcontainer:
        # "blue variables" disabled, we just return a red var all the time.
        # Exception: an operation on a frozen container is constant-foldable.
        ismethod = '.' in operation_name
        return handle_highlevel_operation_novirtual(bookkeeper, ismethod,
                                                    operation_name, False,
                                                    *args_hs)

    # --- the code below is not used any more except by test_annotator.py ---
    if operation_name == 'newlist':
        from pypy.jit.hintannotator.vlist import oop_newlist
        handler = oop_newlist
    else:
        # dispatch on the 'self' argument if it is virtual
        hs_self = args_hs[0]
        args_hs = args_hs[1:]
        type_name, operation_name = operation_name.split('.')
        if not isinstance(hs_self, SomeLLAbstractContainer):
            raise NotImplementedError
        if getattr(hs_self.contentdef, 'type_name', None) != type_name:
            raise NotImplementedError
        try:
            handler = getattr(hs_self.contentdef, 'oop_' + operation_name)
        except AttributeError:
            bookkeeper.warning('missing handler: oop_%s' % (operation_name,))
            raise NotImplementedError

    hs_result = handler(*args_hs)   # which may raise NotImplementedError
    return hs_result

def cannot_follow_call(bookkeeper, graph, args_hs, RESTYPE):
    # the policy prevents us from following the call
    pure_call = bookkeeper.is_pure_graph(graph)
    # when calling pure graphs, consider the call as an operation.
    for hs in args_hs:
        if not isinstance(hs, SomeLLAbstractConstant):
            pure_call = False
            break
    if pure_call:
        # if all arguments are SomeLLAbstractConstant, so can the result be.
        myorigin = bookkeeper.myorigin()
        d = newset({myorigin: True}, *[hs_c.origins for hs_c in args_hs])
        h_res = SomeLLAbstractConstant(RESTYPE, d,
                                       eager_concrete = False,   # probably
                                       myorigin = myorigin)
    else:
        h_res = variableoftype(RESTYPE,
                               cause="non-pure residual call to %s" % graph)
    return h_res

# ____________________________________________________________
#
# Register automatically simple operations

def var_unary(hs_v, *rest_hs):
    RESTYPE = getbookkeeper().current_op_concretetype()
    hs_res = SomeLLAbstractVariable(RESTYPE)
    getbookkeeper().setcause(hs_res, hs_v)
    return hs_res

def var_binary((hs_v1, hs_v2), *rest_hs):
    RESTYPE = getbookkeeper().current_op_concretetype()
    hs_res = SomeLLAbstractVariable(RESTYPE)
    getbookkeeper().setcause(hs_res, (hs_v1, hs_v2))
    return hs_res

def const_unary(llop, hs_c1):
    #XXX unsure hacks
    bk = getbookkeeper()
    origin = bk.myorigin()
    d = setadd(hs_c1.origins, origin)
    RESTYPE = bk.current_op_concretetype()
    hs_res = SomeLLAbstractConstant(RESTYPE, d,
                                    eager_concrete = hs_c1.eager_concrete,
                                    myorigin = origin)
    if hs_c1.is_constant():
        try:
            hs_res.const = llop(RESTYPE, hs_c1.const)
        except Exception:   # XXX not too nice
            pass
    return hs_res

def const_binary(llop, (hs_c1, hs_c2)):
    #XXX unsure hacks
    bk = getbookkeeper()
    origin = bk.myorigin()
    d = newset(hs_c1.origins, hs_c2.origins, {origin: True})
    RESTYPE = bk.current_op_concretetype()
    hs_res = SomeLLAbstractConstant(RESTYPE, d,
                                    eager_concrete = hs_c1.eager_concrete or
                                                     hs_c2.eager_concrete,
                                    myorigin = origin)
    if hs_c1.is_constant() and hs_c2.is_constant():
        try:
            hs_res.const = llop(RESTYPE, hs_c1.const, hs_c2.const)
        except Exception:   # XXX not too nice
            pass
    return hs_res

def setup(oplist, ValueCls, var_fn, ConstantCls, const_fn):
    for name in oplist:
        llop = getattr(lloperation.llop, name)
        if not llop.sideeffects or llop.tryfold:
            if name not in ValueCls.__dict__:
                setattr(ValueCls, name, var_fn)
            if llop.canfold or llop.tryfold:
                if name not in ConstantCls.__dict__:
                    setattr(ConstantCls, name,
                            lambda s, llop=llop: const_fn(llop, s))
setup(UNARY_OPERATIONS,
      SomeLLAbstractValue, var_unary,
      SomeLLAbstractConstant, const_unary)
setup(BINARY_OPERATIONS,
      pairtype(SomeLLAbstractValue, SomeLLAbstractValue), var_binary,
      pairtype(SomeLLAbstractConstant, SomeLLAbstractConstant), const_binary)
del setup
