"""
Mario GameBoy (TM) EmulatOR

Central Unit ProcessOR (Sharp LR35902 CPU)
"""
from pypy.lang.gameboy import constants


class Register(object):
    
    def __init__(self, cpu, value=0):
        self.cpu = cpu
        self.set(value)
        
    def set(self, value, useCycles=True):
        self.value = value & 0xFF
        if (useCycles):
            self.cpu.cycles -= 1
        
    def get(self, useCycles=True):
        return self.value
    
    def add(self, value, useCycles=False):
        self.set(self.get()+1, useCycles)
    
# ___________________________________________________________________________

class DoubleRegister(Register):
    
    cpu = None
    
    def __init__(self, cpu, hi=None, lo=None):
        self.cpu = cpu
        if hi==None:
            self.hi = Register(self.cpu)
        else:
            self.hi = hi
        if lo==None:
            self.lo = Register(self.cpu)
        else:
            self.lo = lo
        
    def set(self, hi=0, lo=None):
        if (lo is None):
            self.setHi(hi >> 8)
            self.setLo(hi & 0xFF)
            self.cpu.cycles += 1
        else:
            self.setHi(hi)
            self.setLo(lo)
            
    def setHi(self, hi=0, useCycles=True):
        self.hi.set(hi, useCycles)
    
    def setLo(self, lo=0, useCycles=True):
        self.lo.set(lo, useCycles)
        
    def get(self):
        return (self.hi.get()<<8) + self.lo.get()
    
    def getHi(self):
        return self.hi.get()
        
    def getLo(self):
        return self.lo.get()
    
    def inc(self):
        self.set(self.get() +1)
        self.cpu.cycles -= 1
        
    def dec(self):
        self.set(self.get() - 1)
        self.cpu.cycles -= 1
        
    def add(self, n=2):
        self.set(self.get() + n)
        self.cpu.cycles -= 2
    
    
# ___________________________________________________________________________

class CPU(object):
    # Registers
    a = 0
    bc = None
    de = None
    f = 0
    hl = None
    sp = None
    pc = None
    af = None

    # Interrupt Flags
    ime = False
    halted  = False
    cycles  = 0

    # Interrupt Controller
    interrupt = None

     # memory Access
    memory = None

    # ROM Access
    rom = []

    def __init__(self, interrupt, memory):
        self.interrupt = interrupt
        self.memory = memory
        self.bc = DoubleRegister(self)
        self.de = DoubleRegister(self)
        self.hl = DoubleRegister(self)
        self.pc = DoubleRegister(self)
        self.sp = DoubleRegister(self)
        self.a = Register(self)
        self.f = Register(self)
        self.af = DoubleRegister(self, self.a, self.f)
        self.reset()

    def reset(self):
        self.a.set(constants.RESET_A)
        self.f.set(constants.RESET_F)
        self.bc.set(constants.RESET_BC)
        self.de.set(constants.RESET_DE)
        self.hl.set(constants.RESET_HL)
        self.sp.set(constants.RESET_SP)
        self.pc.set(constants.RESET_PC)
        self.ime = False
        self.halted = False
        self.cycles = 0
  

    def getIF(self):
        val = 0x00
        if self.ime:
            val = 0x01
        if self.halted:
            val += 0x80
        return val
               
    def getA(self):
        return self.a.get()
    
    def setA(self, value):
        return self.a.set(value)
    
    def getB(self):
        return self.bc.getHi()
        
    def setB(self, value):
        self.bc.setHi(value)
        
    def getC(self):
        return self.bc.getLo()
        
    def setC(self, value):
        self.bc.setLo(value)
        
    def getD(self):
        return self.de.getHi()
        
    def setD(self, value):
        self.de.setHi(value)
        
    def getE(self):
        return self.de.getLo()
        
    def setE(self, value):
        self.de.setLo(value)   
        
    def getF(self):
        return self.f.get()
    
    def setF(self, value):
        return self.f.set(value)
    
    def getH(self):
        return self.hl.getHi()
    
    def setH(self, value):
        self.hl.setHi(value)
        
    def getL(self):
        return self.hl.getLo()
    
    def setL(self, value):
        self.hl.setLo(value)
        
    def getHLi(self):
        return self.read(self.hl.get())
        
    def setHLi(self, value):
        self.write(self.hl.get(), value)
        self.cycles += 1
        
    def setROM(self, banks):
        self.rom = banks

        
    def zFlagAdd(self, s, resetF=False):
        if (resetF):
             self.f.set(0, False)        
        if s == 0:
            self.f.add(constants.Z_FLAG, False)
            
    def cFlagAdd(self, s, compareAnd=0x01, resetF=False):
        if (resetF):
             self.f.set(0, False) 
        if (s & compareAnd) != 0:
            self.f.add(constants.C_FLAG, False)

    def emulate(self, ticks):
        self.cycles += ticks
        self.interrupt()
        while (self.cycles > 0):
            self.execute()

     # Interrupts
     # XXX this doesn't work, you cannot have two methods with the same name
     # and different numbers of parameters
     # another problem is that the attribute self.parameter cannot have the
     # same name as a method or you will confuse yourself in major ways (Python
     # is lookup-based, not send-based)
    def interrupt(self):
        if (self.halted):
            if (self.interrupt.isPending()):
                self.halted = False
                # Zerd no Densetsu
                self.cycles -= 4
            elif (self.cycles > 0):
                self.cycles = 0
        if (self.ime and self.interrupt.isPending()):
            if (self.interrupt.isPending(constants.VBLANK)):
                self.interrupt(0x40)
                self.interrupt.lower(constants.VBLANK)
            elif (self.interrupt.isPending(constants.LCD)):
                self.interrupt(0x48)
                self.interrupt.lower(constants.LCD)
            elif (self.interrupt.isPending(constants.TIMER)):
                self.interrupt(0x50)
                self.interrupt.lower(constants.TIMER)
            elif (self.interrupt.isPending(constants.SERIAL)):
                self.interrupt(0x58)
                self.interrupt.lower(constants.SERIAL)
            elif (self.interrupt.isPending(constants.JOYPAD)):
                self.interrupt(0x60)
                self.interrupt.lower(constants.JOYPAD)

    def interrupt(self, address):
        self.ime = False
        self.call(address)

     # Execution
    def fetchExecute(self):
        # these global statements have no effect
        global FETCH_EXECUTE_OP_CODES
        FETCH_EXECUTE_OP_CODES[self.fetch()](self)
        
    def execute(self, opCode):
        global OP_CODES
        OP_CODES[opCode](self)
        
        
    def reverseArgumentsDoubleRegister(self, register, getter):
        pass
    
     # memory Access, 1 cycle
    def read(self, hi, lo=None):
        address = hi
        if lo != None:
            address(hi << 8) + lo
        self.cycles -= 1
        return self.memory.read(address)

    # 2 cycles
    def write(self, address, data):
        self.memory.write(address, data)
        self.cycles -= 2


     # Fetching  1 cycle
    def fetch(self):
        self.cycles += 1
        if (self.pc.get() <= 0x3FFF):
            self.pc.inc() # 2 cycles
            return self.rom[self.pc.get()] & 0xFF
        data = self.memory.read(self.pc.get())
        self.pc.inc() # 2 cycles
        return data

     # Stack, 2 cycles
    def push(self, data):
        self.sp.dec() # 2 cycles
        self.memory.write(self.sp.get(), data)
        
     # PUSH rr 4 cycles
    def pushDoubleRegister(self, register):
        self.push(register.getHi()) # 2 cycles
        self.push(register.getLo()) # 2 cycles

    # 1 cycle
    def pop(self):
        data = self.memory.read(self.sp.get())
        self.sp.inc() # 2 cycles
        self.cycles += 1
        return data
    
     # 3 cycles
    def popDoubleRegister(self, register, getter):
        b = getter() # 1 cycle
        a = getter() # 1 cycle
        register.set(a, b) # 2 cycles
        self.cycles += 1
        
    # 4 cycles
    def call(self, address):
        self.push(self.pc.getHi()) # 2 cycles
        self.push(self.pc.getLo()) # 2 cycles
        self.pc.set(address)       # 1 cycle
        self.cycles += 1
        
     # 1 cycle
    def ld(self, getter, setter):
        setter(getter()) # 1 cycle

     # ALU, 1 cycle
    def addA(self, data):
        s = (self.a.get() + data) & 0xFF
        self.zFlagAdd(s, resetF=True)
        if s < self.a.get():
            self.f.add(constants.C_FLAG, False)
        if (s & 0x0F) < (self.a.get() & 0x0F):
            self.f.add(constants.H_FLAG, False)
        self.a.set(s) # 1 cycle
        
    # 2 cycles
    def addHL(self, register):
        s = (self.hl.get() + register.get()) & 0xFFFF
        self.f.set((self.f & constants.Z_FLAG), False)
        if ((s >> 8) & 0x0F) < (self.hl.getHi() & 0x0F):
            self.f.add(constants.H_FLAG, False)
        if  s < self.hl.get():
            self.f.add(constants.C_FLAG, False)
        self.cycles -= 1
        self.hl.set(s); # 1 cycle

    # 1 cycle
    def adc(self, getter):
        s = self.a + getter() + ((self.f & constants.C_FLAG) >> 4)
        self.f.set(0, False)
        if (s & 0xFF) == 0:
            self.f.add(constants.Z_FLAG , False)
        if s >= 0x100:
            self.f.add(constants.C_FLAG, False)
        if ((s ^ self.a ^ getter()) & 0x10) != 0:
            self.f.add(constants.H_FLAG, False)
        self.a.set(s & 0xFF)  # 1 cycle

    # 1 cycle
    def sbc(self, getter):
        s = self.a - getter() - ((self.f & constants.C_FLAG) >> 4)
        self.f.set(constants.N_FLAG, False)
        if (s & 0xFF) == 0:
            self.f.add(constants.Z_FLAG , False)
        if (s & 0xFF00) != 0:
            self.f.add(constants.C_FLAG, False)
        if ((s ^ self.a ^ getter()) & 0x10) != 0:
            self.f.add(constants.H_FLAG, False)
        self.a.set(s & 0xFF)  # 1 cycle
        
    # 1 cycle
    def sub(self, getter):
        s = (self.a - getter()) & 0xFF
        self.f.set(constants.N_FLAG, False)
        self.zFlagAdd(s)
        if s > self.a:
            self.f.add(constants.C_FLAG, False)
        if (s & 0x0F) > (self.a & 0x0F):
            self.f.add(constants.H_FLAG, False)
        self.a.set(s)  # 1 cycle

    # 1 cycle
    def cpA(self, getter):
        s = (self.a - getter()) & 0xFF
        self.f.set(constants.N_FLAG)  # 1 cycle
        self.zFlagAdd(self.a)
        if s > self.a:
            self.f.add(constants.C_FLAG, False)
        if (s & 0x0F) > (self.a & 0x0F):
            self.f.add(constants.H_FLAG, False)

    # 1 cycle
    def AND(self, getter):
        self.a.set(self.a & getter())  # 1 cycle
        self.zFlagAdd(self.a, resetF=True)

    # 1 cycle
    def XOR(self, getter):
        self.a.set( self.a ^ getter())  # 1 cycle
        self.zFlagAdd(self.a, resetF=True)

    # 1 cycle
    def OR(self, getter):
        self.a.set(self.a | getter())  # 1 cycle
        self.zFlagAdd(self.a, resetF=True)

    # 1 cycle
    def inc(self, getter, setter):
        data = (getter() + 1) & 0xFF
        self.decIncFlagFinish(data)

    # 1 cycle
    def dec(self, getter, setter):
        data = (getter() - 1) & 0xFF
        self.decIncFlagFinish(data) 
        self.f.add(constants.N_FLAG, False)
     
    def decIncFlagFinish(data):
        self.f.set(0) # 1 cycle
        self.zFlagAdd(data)
        if (data & 0x0F) == 0x0F:
            self.f.add(constants.H_FLAG, False)
        self.f.add((self.f & constants.C_FLAG), False)
        setter(data)

    # 1 cycle
    def rlc(self, getter, setter):
        s = ((getter() & 0x7F) << 1) + ((getter() & 0x80) >> 7)
        flagsAndSetterFinish(s, getter, 0x80)

    # 1 cycle
    def rl(self, getter, setter):
        s = ((getter() & 0x7F) << 1)
        if (self.f & constants.C_FLAG) != 0:
            s += 0x01
        flagsAndSetterFinish(s, getter, 0x80) # 1 cycle

    # 1 cycle
    def rrc(self, getter, setter):
        s = (getter() >> 1) + ((getter() & 0x01) << 7)
        flagsAndSetterFinish(s, getter) # 1 cycle

    # 1 cycle
    def rr(self, getter, setter):
        s = (getter() >> 1) + ((self.f & constants.C_FLAG) << 3)
        flagsAndSetterFinish(s, getter) # 1 cycle

    # 2 cycles
    def sla(self, getter, setter):
        s = (getter() << 1) & 0xFF
        flagsAndSetterFinish(s, getter, 0x80) # 1 cycle

    # 1 cycle
    def sra(self, getter, setter):
        s = (getter() >> 1) + (getter() & 0x80)
        flagsAndSetterFinish(s, getter) # 1 cycle

    # 1 cycle
    def srl(self, getter, setter):
        s = (getter() >> 1)
        flagsAndSetterFinish(s, getter) # 1 cycle
        
     # 1 cycle
    def flagsAndSetterFinish(self, s, setter, compareAnd=0x01):
        self.f.set(0) # 1 cycle
        self.zFlagAdd(s)
        # XXX where does "getter" come from here? should be "setter"?
        self.cFlagAdd(getter(), compareAnd)
        setter(s)

    # 1 cycle
    def swap(self, getter, setter):
        s = ((getter() << 4) & 0xF0) + ((getter() >> 4) & 0x0F)
        self.f.set(0) # 1 cycle
        self.zFlagAdd(s)
        setter(s)

    # 2 cycles
    def bit(self, getter, setter, n):
        self.f.set((self.f & constants.C_FLAG) + constants.H_FLAG, False)
        if (getter() & (1 << n)) == 0:
            self.f.add(constants.Z_FLAG, False)
        self.cycles -= 2

     # RLCA 1 cycle
    def rlca(self):
        self.cFlagAdd(self.a, 0x80, resetF=True)
        self.a.set(((self.a & 0x7F) << 1) + ((self.a & 0x80) >> 7))

     # RLA  1 cycle
    def rla(self):
        s = ((self.a & 0x7F) << 1)
        if (self.f & constants.C_FLAG) != 0:
            s +=  0x01
        self.cFlagAdd(self.a, 0x80, resetF=True)
        self.a.set(s) #  1 cycle

     # RRCA 1 cycle
    def rrca(self):
        self.cFlagAdd(self.a, resetF=True)
        self.a.set(((self.a >> 1) & 0x7F) + ((self.a << 7) & 0x80)) #1 cycle

     # RRA 1 cycle
    def rra(self):
        s = ((self.a >> 1) & 0x7F)
        if (self.f & constants.C_FLAG) != 0:
            s += 0x80
        self.cFlagAdd(self.a, resetF=True)
        self.a.set(s) # 1 cycle

    # 2 cycles
    def set(self, getter, setter, n):
        self.cycles -= 1                  # 1 cycle
        setter(getter() | (1 << n)) # 1 cycle
        
    # 1 cycle
    def res(self, getter, setter, n):
        setter(getter() & (~(1 << n))) # 1 cycle
        

     # LD A,(nnnn), 4 cycles
    def ld_A_mem(self):
        lo = self.fetch() # 1 cycle
        hi = self.fetch() # 1 cycle
        self.a.set(self.read(hi, lo))  # 1+1 cycles

    # 2 cycles
    def ld_BCi_A(self):
        self.write(self.bc.get(), self.a.get());
        
    def ld_DEi_A(self):
        self.write(self.de.get(), self.a.get());
           
    def ld_A_BCi(self):
        self.a.set(self.read(self.bc.get()))

    def load_A_DEi(self):
        self.a.set(self.read(self.de.get()))

     # LD (rr),A  2 cycles
    def ld_dbRegisteri_A(self, register):
        self.write(register.get(), self.a.get()) # 2 cycles

     # LD (nnnn),SP  5 cycles
    def load_mem_SP(self):
        lo = self.fetch() # 1 cycle
        hi = self.fetch() # 1 cycle
        address = (hi << 8) + lo
        self.write(address, self.sp.getLo())  # 2 cycles
        self.write((address + 1) & 0xFFFF, self.sp.getHi()) # 2 cycles
        self.cycles += 1

     # LD (nnnn),A  4 cycles
    def ld_mem_A(self):
        lo = self.fetch() # 1 cycle
        hi = self.fetch() # 1 cycle
        self.write(hi, lo, self.a.get()) # 2 cycles

     # LDH A,(nn) 3 cycles
    def ldh_A_mem(self):
        self.a.set(self.read(0xFF00 + self.fetch())) # 1+1+1 cycles
        
     # LDH A,(C) 2 cycles
    def ldh_A_Ci(self):
        self.a.set(self.read(0xFF00 + self.bc.getLo())) # 1+2 cycles
        
     # LDI A,(HL) 2 cycles
    def ldi_A_HLi(self):
        self.a.set(self.read(self.hl.get())) # 1 cycle
        self.hl.inc()# 2 cycles
        self.cycles += 1
        
     # LDD A,(HL)  2 cycles
    def ldd_A_HLi(self):
        self.a.set(self.read(self.hl.get())) # 1 cycle
        self.hl.dec() # 2 cycles
        self.cycles += 1
        
     # LDH (nn),A 3 cycles
    def ldh_mem_A(self):
        self.write(0xFF00 + self.fetch(), self.a.get()) # 2 + 1 cycles

     # LDH (C),A 2 cycles
    def ldh_Ci_A(self):
        self.write(0xFF00 + self.bc.getLo(), self.a.get()) # 2 cycles
        
     # LDI (HL),A 2 cycles
    def ldi_HLi_A(self):
        self.write(self.hl.get(), self.a.get()) # 2 cycles
        self.hl.inc() # 2 cycles
        self.cycles += 2

     # LDD (HL),A  2 cycles
    def ldd_HLi_A(self):
        self.write(self.hl.get(), self.a) # 2 cycles
        self.hl.dec() # 2 cycles
        self.cycles += 2

     # LD SP,HL 2 cycles
    def ld_SP_HL(self):
        self.sp.set(self.hl.get()) # 1 cycle
        self.cycles -= 1

    def cpl(self):
        self.a.set(self.a.get() ^ 0xFF, False)
        self.f.set(self.f.get() | (constants.N_FLAG + constants.H_FLAG))

     # DAA 1 cycle
    def daa(self):
        delta = 0
        if ((self.f.get() & constants.H_FLAG) != 0 or (self.a.get() & 0x0F) > 0x09):
            delta |= 0x06
        if ((self.f.get() & constants.C_FLAG) != 0 or (self.a.get() & 0xF0) > 0x90):
            delta |= 0x60
        if ((self.a.get() & 0xF0) > 0x80 and (self.a.get() & 0x0F) > 0x09):
            delta |= 0x60
        if ((self.f.get() & constants.N_FLAG) == 0):
            self.a.set((self.a.get() + delta) & 0xFF) # 1 cycle
        else:
            self.a.set((self.a.get() - delta) & 0xFF) # 1 cycle
        self.f.set((self.f.get() & constants.N_FLAG), False)
        if delta >= 0x60:
            self.f.add(constants.C_FLAG, False)
        self.zFlagAdd(self.a.get())

     # INC rr
    def incDoubleRegister(self, register):
        register.inc()

     # DEC rr
    def decDoubleRegister(self, register):
        register.dec()

     # ADD SP,nn 4 cycles
    def add_SP_nn(self):
        self.sp.set(self.SP_nn()) # 1+1 cycle
        self.cycles -= 2

     # LD HL,SP+nn   3  cycles
    def ld_HL_SP_nn(self):
        self.hl.set(self.SP_nn()) # 1+1 cycle
        self.cycles -= 1

    # 1 cycle
    def SP_nn(self):
        offset = self.fetch() # 1 cycle
        s = (self.sp.get() + offset) & 0xFFFF
        self.f.set(0, False)
        if (offset >= 0):
            if s < self.sp.get():
                self.f.add(constants.C_FLAG, False)
            if (s & 0x0F00) < (self.sp.get() & 0x0F00):
                self.f.add(constants.H_FLAG, False)
        else:
            if s > self.sp.get():
                self.f.add(constants.C_FLAG, False)
            if (s & 0x0F00) > (self.sp.get() & 0x0F00):
                self.f.add(constants.H_FLAG, False)

     # CCF/SCF
    def ccf(self):
        self.f.set((self.f & (constants.Z_FLAG | constants.C_FLAG)) ^ constants.C_FLAG, False)

    def scf(self):
        self.f.set((self.f & constants.Z_FLAG) | constants.C_FLAG, False)

     # NOP 1 cycle
    def nop(self):
        self.cycles -= 1

     # LD PC,HL, 1 cycle

     # JP nnnn, 4 cycles
    def jp_nnnn(self):
        lo = self.fetch() # 1 cycle
        hi = self.fetch() # 1 cycle
        self.pc.set(hi,lo) # 2 cycles

     # JP cc,nnnn 3,4 cycles
    def jp_cc_nnnn(cc):
        if (cc):
            self.jp_nnnn() # 4 cycles
        else:
            self.pc.add(2) # 3 cycles

     # JR +nn, 3 cycles
    def jr_nn(self):
        self.pc.add(self.fetch()) # 3 + 1 cycles
        self.cycles += 1

     # JR cc,+nn, 2,3 cycles
    def jr_cc_nn(cc):
        if (cc):
            self.pc.add(self.fetch()) # 3 cycles
        else:
            self.pc.inc() # 2 cycles
    
     # CALL nnnn, 6 cycles
    def call_nnnn(self):
        lo = self.fetch() # 1 cycle
        hi = self.fetch() # 1 cycle
        self.call((hi << 8) + lo)  # 4 cycles

     # CALL cc,nnnn, 3,6 cycles
    def call_cc_nnnn(cc):
        if (cc):
            self.call_nnnn() # 6 cycles
        else:
            self.pc.add(2) # 3 cycles
    
    def isNZ(self):
        return (self.f & constants.Z_FLAG) == 0

    def isNC(self):
        return (self.f & constants.C_FLAG) == 0

    def isZ(self):
        return (self.f & constants.Z_FLAG) != 0

    def isC(self):
        return (self.f & constants.C_FLAG) != 0

     # RET 4 cycles
    def ret(self):
        lo = self.pop() # 1 cycle
        hi = self.pop() # 1 cycle
        self.pc.set(hi, lo) # 2 cycles

     # RET cc 2,5 cycles
    def ret_cc(cc):
        if (cc):
            self.ret() # 4 cycles
            # FIXME maybe this should be the same
            self.cycles -= 1
        else:
            self.cycles -= 2

     # RETI 4 cycles
    def reti(self):
        self.ret() # 4 cycles
         # enable interrupts
        self.ime = True
        # execute next instruction
        self.execute()
        # check pending interrupts
        self.interrupt()

     # RST nn 4 cycles
    def rst(self, nn):
        self.call(nn) # 4 cycles

     # DI/EI 1 cycle
    def di(self):
        # disable interrupts
        self.ime = False
        self.cycles -= 1; 

    # 1 cycle
    def ei(self): 
        # enable interrupts
        self.ime = True
        self.cycles -= 1
        # execute next instruction
        self.execute()
        # check pending interrupts
        self.interrupt()

     # HALT/STOP
    def halt(self):
        self.halted = True
        # emulate bug when interrupts are pending
        if (not self.ime and self.interrupt.isPending()):
            self.execute(self.memory.read(self.pc.get()))
        # check pending interrupts
        self.interrupt()

    # 0 cycles
    def stop(self):
        self.cycles += 1
        self.fetch()



FIRST_ORDER_OP_CODES = [
    (0x00, CPU.nop),
    (0x08, CPU.load_mem_SP),
    (0x10, CPU.stop),
    (0x18, CPU.jr_nn),
    (0x02, CPU.ld_BCi_A),
    (0x12, CPU.ld_DEi_A),
    (0x22, CPU.ldi_HLi_A),
    (0x32, CPU.ldd_HLi_A),
    (0x0A, CPU.ld_A_BCi),
    (0x1A, CPU.load_A_DEi),
    (0x2A, CPU.ldi_A_HLi),
    (0x3A, CPU.ldd_A_HLi),
    (0x07, CPU.rlca),
    (0x0F, CPU.rrca),
    (0x17, CPU.rla),
    (0x1F, CPU.rra),
    (0x27, CPU.daa),
    (0x2F, CPU.cpl),
    (0x37, CPU.scf),
    (0x3F, CPU.ccf),
    (0x76, CPU.halt),
    (0xF3, CPU.di),
    (0xFB, CPU.ei),
    (0xE2, CPU.ldh_Ci_A),
    (0xEA, CPU.ld_mem_A),
    (0xF2, CPU.ldh_A_Ci),
    (0xFA, CPU.ld_A_mem),
    (0xC3, CPU.jp_nnnn),
    (0xC9, CPU.ret),
    (0xD9, CPU.reti),
    (0xE9, lambda s: CPU.ld(s, CPU.hl, CPU.pc)),
    (0xF9, CPU.ld_SP_HL),
    (0xE0, CPU.ldh_mem_A),
    (0xE8, CPU.add_SP_nn),
    (0xF0, CPU.ldh_A_mem),
    (0xF8, CPU.ld_HL_SP_nn),
    (0xCB, CPU.fetchExecute),
    (0xCD, CPU.call_nnnn),
    (0xC6, lambda s: CPU.addA(s, CPU.fetch(s))),
    (0xCE, lambda s: CPU.adc(s, CPU.fetch(s))),
    (0xD6, lambda s: CPU.sub(s, CPU.fetch(s))),
    (0xDE, lambda s: CPU.sbc(s, CPU.fetch(s))),
    (0xE6, lambda s: CPU.AND(s, CPU.fetch(s))),
    (0xEE, lambda s: CPU.XOR(s, CPU.fetch(s))),
    (0xF6, lambda s: CPU.OR(s, CPU.fetch(s))),
    (0xFE, lambda s: CPU.cpA(s, CPU.fetch(s))),
    (0xC7, lambda s: CPU.rst(s, 0x00)),
    (0xCF, lambda s: CPU.rst(s, 0x08)),
    (0xD7, lambda s: CPU.rst(s, 0x10)),
    (0xDF, lambda s: CPU.rst(s, 0x18)),
    (0xE7, lambda s: CPU.rst(s, 0x20)),
    (0xEF, lambda s: CPU.rst(s, 0x28)),
    (0xF7, lambda s: CPU.rst(s, 0x30)),
    (0xFF, lambda s: CPU.rst(s, 0x38)),
]

REGISTER_GROUP_OP_CODES = [
    (0x04, 0x08, CPU.inc),
    (0x05, 0x08, CPU.dec),    
    (0x80, 0x01, CPU.addA),    
    (0x88, 0x01, CPU.adc),    
    (0x90, 0x01, CPU.sub),    
    (0x98, 0x01, CPU.sbc),    
    (0xA0, 0x01, CPU.AND),    
    (0xA8, 0x01, CPU.XOR),    
    (0xB0, 0x01, CPU.OR),
    (0xB8, 0x01, CPU.cpA),
    #(0x06, 0x08, CPU.ld_nn),
    (0x40, 0x01, CPU.res, range(0, 8))
]

REGISTER_OP_CODES = [ 
    (0x01, 0x10, lambda s: CPU.pop_dbRegister(s, CPU.fetch), [CPU.bc, CPU.de, CPU.hl, CPU.sp]),
    (0x09, 0x10, CPU.addHL,  [CPU.bc, CPU.de, CPU.hl, CPU.sp]),
    (0x03, 0x10, CPU.inc,  [CPU.bc, CPU.de, CPU.hl, CPU.sp]),
    (0x0B, 0x10, CPU.dec,  [CPU.bc, CPU.de, CPU.hl, CPU.sp]),
    
    #(0xC0, 0x08, CPU.ret, [NZ, Z, NC, C]),
    #(0xC2, 0x08, CPU.jp_nnnn, [NZ, Z, NC, C]),
    #(0xC4, 0x08, CPU.call_nnnn, [NZ, Z, NC, C]),
    #(0x20, 0x08, CPU.jr_nn, [NZ, Z, NC, C]),"""
    
    (0xC1, 0x10, CPU.pop,  [CPU.bc, CPU.de, CPU.hl, CPU.af]),
    (0xC5, 0x10, CPU.push, [CPU.bc, CPU.de, CPU.hl, CPU.af])
]

SECOND_ORDER_REGISTER_OP_CODES = [
    (0x00, 0x01, CPU.rlc),    
    (0x08, 0x01, CPU.rrc),    
    (0x10, 0x01, CPU.rl),    
    (0x18, 0x01, CPU.rr),    
    (0x20, 0x01, CPU.sla),    
    (0x28, 0x01, CPU.sra),    
    (0x30, 0x01, CPU.swap),    
    (0x38, 0x01, CPU.srl),
    (0x40, 0x01, CPU.bit, range(0, 8)),    
    (0xC0, 0x01, CPU.set, range(0, 8)),
    (0x80, 0x01, CPU.res, range(0, 8))         
]


GROUP_CODES_GETTERS = (CPU.getB, CPU.getC, CPU.getD, CPU.getE, CPU.getH, CPU.getL, CPU.getHLi, CPU.getA)
GROUP_CODES_SETTERS = (CPU.setB, CPU.setC, CPU.setD, CPU.setE, CPU.setH, CPU.setL, CPU.setHLi, CPU.setA)

def create_group_op_codes(table):
    opCodes = [None] * 0xFF;
    for entry in table:
        startCode = entry[0]
        step = entry[1]
        method = entry[2]
        getters = GROUP_CODES_GETTERS
        if len(entry) == 4:
            for i in range(0, 8):
                for n in entry[3]:
                    index = startCode+step*i
                    opCodes[index] = (index, lambda me: method(me, GROUP_CODES_GETTERS[i], GROUP_CODES_SETTERS[i], n))
        else:
            for i in range(0, 8):
                index = startCode+step*i
                opCodes[index] = (index, lambda me: method(me, GROUP_CODES_GETTERS[i], GROUP_CODES_SETTERS[i]))
    return opCodes

FIRST_ORDER_OP_CODES.extend(create_group_op_codes(REGISTER_GROUP_OP_CODES))
SECOND_ORDER_OP_CODES = create_group_op_codes(SECOND_ORDER_REGISTER_OP_CODES)

def create_register_op_codes():
    # not necessary to build a list, you can nicely use a generator here
    opCodes = [];
    for entry in REGISTER_OP_CODES:
         startCode = entry[0]
         step = entry[1]
         commandBase = entry[2]
         changing = entry[3]
    return opCodes

FIRST_ORDER_OP_CODES.extend(create_register_op_codes())


def initialize_op_code_table(table):
    result = [None] * 256
    for entry in  table:
        if entry is None:
            continue
        if len(entry) == 2:
            positions = [entry[0]]
        else:
            positions = range(entry[0], entry[1]+1)
        for pos in positions:
            result[pos] = entry[-1]
    return result
   
OP_CODES = initialize_op_code_table(FIRST_ORDER_OP_CODES)
FETCH_EXECUTE_OP_CODES = initialize_op_code_table(SECOND_ORDER_OP_CODES)
