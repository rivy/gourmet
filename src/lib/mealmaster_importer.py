#!/usr/bin/python
import importer, re, convert, os.path, string
import rmetakit, check_encodings, array
from gdebug import debug,TimeAction
from gglobals import gt
from gettext import gettext as _

class mmf_constants:
    def __init__ (self):
        self.committed = False
        self.recattrs={'Title':'title',
                       'Categories':'category',
                       'Servings':'servings',
                       'Source':'source',
                       'Recipe by':'source',
                       'Yield':'servings',
                       'Preparation Time':'preptime',
                       }
        
        self.unit_conv = {'ts':'tsp.',
                          'tb':'tbs.',
                          'sm':'small',
                          'md':'medium',
                          'ea':'',
                          'lg':'large',
                          'c':'c.',
                          'pn':'pinch',
                          'ds':'dash',
                          'T' : 'tbs.',
                          't' : 'tsp.',
                          'pk' : 'package',
                          'x' : '',
                          'ea' : '',
                          't' : 'tsp.',
                          }
        self.unit_convr = {}
        for k,v in self.unit_conv.items():
            self.unit_convr[v]=k

        

mmf=mmf_constants()
class mmf_importer (importer.importer):
    def __init__ (self,rd,filename='Data/mealmaster.mmf',
                  progress=None, source=None,threaded=True,
                  two_col_minimum=38):
        testtimer = TimeAction('mealmaster_importer.__init__',10)
        debug("mmf_importer start  __init__ ",5)
        """filename is the file to parse. rd is the recData instance
        to start with.  progress is a function we tell about our
        progress to (we hand it a single arg)."""
        self.rec={}
        self.source=source
        self.header=False
        self.instr=""
        self.ingrs=[]
        self.ing_added=False
        self.compile_regexps()
        self.fn = filename
        self.progress = progress
        self.unit_length = 2
        self.two_col_minimum = two_col_minimum
        self.last_line_was = None
        importer.importer.__init__(self,rd=rd,threaded=threaded)        
        testtimer.end()
        
    def run (self):
        testtimer = TimeAction('mealmaster_importer.run',10)
        #self.file=open(self.fn,'r')
        self.base=os.path.split(self.fn)[1]
        #ll=self.file.readlines() #slurp
        ll = check_encodings.get_file(self.fn)
        tot=len(ll)
        for n in range(tot):
            # we do the loop this way so we can
            # conveniently report our progress to
            # the outside world :)
            l=ll[n]
            # we update our progress bar every 15 lines
            if n % 15 == 0:
                prog= float(n)/float(tot)
                if self.progress:
                    msg = _("Imported %s recipes.")%(len(self.added_recs))
                    self.progress(prog,msg)
            self.handle_line(l)
        # commit the last recipe if need be
        if self.rec:
            self.commit_rec()
        self.progress(1,_("Mealmaster import completed."))
        importer.importer.run(self)
        testtimer.end()
        
    def compile_regexps (self):
        testtimer = TimeAction('mealmaster_importer.compile_regexps',10)
        debug("start compile_regexps",5)
        self.start_matcher = re.compile("^([M-][M-][M-][M-][M-])-*\s*(Recipe|[Mm]eal-?[Mm]aster).*")
        self.end_matcher = re.compile("^[M-][M-][M-][M-][M-]\s*$")
        self.group_matcher = re.compile("^([M-][M-][M-][M-][M-])-*\s*([^-]+)\s*-*")
        self.blank_matcher = re.compile("^\s*$")
        self.ing_cont_matcher = re.compile("^\s*[-;]")
        self.ing_opt_matcher = re.compile("(.+?)\s*\(?\s*[Oo]ptional\)?\s*$")
        self.ing_or_matcher = re.compile("^[- ]*[Oo][Rr][- ]*$")
        self.variation_matcher = re.compile("^\s*([Vv][Aa][Rr][Ii][Aa][Tt][Ii][Oo][Nn]|[Hh][Ii][Nn][Tt]|[Nn][Oo][Tt][Ee])[Ss]?:.*")
        # a crude ingredient matcher -- we look for two numbers, intermingled with spaces
        # followed by a space or more, followed by a two digit unit (or spaces)
        self.ing_num_matcher = re.compile("^\s*[0-9]+[0-9/ -]+\s+[A-Za-z ][A-Za-z ] .*")
        self.amt_field_matcher = re.compile("^[0-9- /]+$")
        # we build a regexp to match anything that looks like
        # this: ^\s*ATTRIBUTE: Some entry of some kind...$
        attrmatch="^\s*("
        for k in mmf.recattrs.keys():
            attrmatch += "%s|"%re.escape(k)
        attrmatch="%s):\s*(.*)\s*$"%attrmatch[0:-1]
        self.attr_matcher = re.compile(attrmatch)
        testtimer.end()
        
    def handle_line (self,l):
        testtimer = TimeAction('mealmaster_importer.handle_line',10)
        """We're quite loose at handling mealmaster files. We look at
        each line and determine what it is most likely to be: ingredients
        and instructions can be intermingled: instructions will simply be
        added to the instructions and ingredients to the ingredient list.
        This may result in loss of information (for instructions that specifically
        follow ingredients) or in mis-parsing (for instructions that look like
        ingredients). But we're following, more or less, the specs laid out
        here <http://phprecipebook.sourceforge.net/docs/MM_SPEC.DOC>"""
        debug("start handle_line",10)
        gt.gtk_update()
        if self.start_matcher.match(l):
            debug("recipe start %s"%l,4)
            self.new_rec()
            self.last_line_was = 'new_rec'
            self.in_variation = False
            return
        if self.end_matcher.match(l):
            debug("recipe end %s"%l,4)            
            self.commit_rec()
            self.last_line_was = 'end_rec'
            return
        groupm = self.group_matcher.match(l)
        if groupm:
            debug("new group %s"%l,4)            
            self.handle_group(groupm)
            self.last_line_was = 'group'
            return
        attrm = self.attr_matcher.match(l)
        if attrm:        
            # a match for an attribute has two groups,
            # (ATTRIBUTE): (VALUE)
            attr,val = attrm.groups()
            debug("attribute %s (%s:%s)"%(l,attr,val),4)
            self.rec[mmf.recattrs[attr]]=val.strip()
            self.last_line_was = 'attr'
            return

        if not self.instr and self.blank_matcher.match(l):
            debug('ignoring blank line before instructions',4)
            self.last_line_was = 'blank'
            return
        if self.variation_matcher.match(l):
            debug('in variation',4)
            self.in_variation = True
        if self.is_ingredient(l) and not self.in_variation:
            contm = self.ing_cont_matcher.match(l)
            if contm:
                # only continuations after ingredients are ingredients
                if self.ingrs and self.last_line_was == 'ingr':
                    debug('continuing %s'%self.ingrs[-1][0],4)
                    continuation = " %s"%l[contm.end():].strip()
                    self.ingrs[-1][0] += continuation
                    self.last_line_was = 'ingr'
                else:
                    self.instr += l
                    self.last_line_was = 'instr'
            else:
                self.last_line_was = 'ingr'
                self.ingrs.append([l,self.group])
        else:
            ## otherwise, we assume a line of instructions
            if self.in_variation:
                debug('Adding to modifications: %s'%l,4)
                self.last_line_was = 'mod'
                self.mod += l
            else:
                debug('Adding to instructions: %s'%l,4)
                self.last_line_was = 'instr'
                self.instr = self.instr.strip()+"\n"
                self.instr += l
                testtimer.end()
                
    def is_ingredient (self, l):
        testtimer = TimeAction('mealmaster_importer.is_ingredient',10)
        """We're going to go with a somewhat hackish approach
        here. Once we have the ingredient list, we can determine
        columns more appropriately.  For now, we'll assume that a
        field that starts with at least 5 blanks (the specs suggest 7)
        or a field that begins with a numeric value is an ingredient"""
        if self.ing_num_matcher.match(l):
            testtimer.end()
            return True
        if len(l) >= 7 and self.blank_matcher.match(l[0:5]):
            testtimer.end()
            return True

        
    def new_rec (self):
        testtimer = TimeAction('mealmaster_importer.new_rec',10)
        debug("start new_rec",5)
        if self.rec:
            # this shouldn't happen if recipes are ended properly
            # but we'll be graceful if a recipe starts before another
            # has ended... 
            self.commit_rec()
        self.committed=False
        self.start_rec(base=self.base)
        debug('resetting instructions',5)
        self.instr=""
        self.mod = ""
        self.ingrs=[]
        self.header=False
        testtimer.end()
        
    def commit_rec (self):
        testtimer = TimeAction('mealmaster_importer.commit_rec',10)
        if self.committed: return
        debug("start _commit_rec",5)
        # unwrap lines
        #ll=re.split('\n\s*\n',self.instr)
        #self.instr=string.join(ll,'GOURMETS_UGLY_HACK')
        #self.instr.replace('\n',' ')
        #self.instr.replace('GOURMETS_UGLY_HACK','\n')
        self.rec['instructions']=self.instr
        if self.mod:
            self.rec['modifications']=self.mod
        self.parse_inglist()
        if self.source:
            self.rec['source']=self.source
        importer.importer.commit_rec(self)
        # blank rec
        self.committed = True
        testtimer.end()
        
    def handle_group (self, groupm):
        testtimer = TimeAction('mealmaster_importer.handle_group',10)
        debug("start handle_group",10)
        # the only group of the match will contain
        # the name of the group. We'll put it into
        # a more sane title case (MealMaster defaults
        # to all caps
        name = groupm.groups()[1].title()
        self.group=name
        testtimer.end()
        # a blank line before a group could fool us into thinking
        # we were in instructions. If we see a group heading,
        # we know that's not the case!


    def find_ing_fields (self):
        testtimer = TimeAction('mealmaster_importer.find_ing_fields',10)
        all_ings = [i[0] for i in self.ingrs]
        fields = find_fields(all_ings)
        fields_is_numfield = fields_match(all_ings,fields,self.amt_field_matcher)
        #fields = [[r,field_match(all_ings,r,self.amt_field_matcher)] for r in find_fields(all_ings)]
        aindex,afield = self.find_amt_field(fields,fields_is_numfield)
        if aindex != None:
            fields = fields[aindex+1:]
            fields_is_numfield = fields_is_numfield[aindex+1:]
        ufield = self.find_unit_field(fields,fields_is_numfield)
        if ufield:
            fields = fields[1:]
            fields_is_numfield = fields_is_numfield[1:]
        ifield = [fields[0][0],None]
        retval = [[afield,ufield,ifield]]
        sec_col_fields = filter(lambda x: x[0]>self.two_col_minimum,fields)        
        if sec_col_fields:
            ibase = fields.index(sec_col_fields[0])
            while sec_col_fields and not fields_is_numfield[ibase]:
                ibase += 1
                sec_col_fields = sec_col_fields[1:]
                # if we might have a 2nd column...
        if sec_col_fields and len(sec_col_fields) > 2:            
            fields_is_numfield = fields_is_numfield[ibase:]
            aindex2,afield2 = self.find_amt_field(sec_col_fields,fields_is_numfield)
            if aindex2 != None and len(sec_col_fields[aindex2+1:]) >= 1:
                # then it's a go! Shift our first ifield
                retval[0][2]=[ifield[0],fields[ibase-1][1]]
                sec_col_fields = sec_col_fields[aindex2 + 1:]
                fields_is_numfield = fields_is_numfield[aindex2+1:]
                ufield2 = self.find_unit_field(sec_col_fields,fields_is_numfield)
                if ufield2:
                    sec_col_fields=sec_col_fields[1:]
                    fields_is_numfield = fields_is_numfield[1:]
                ifield2 = sec_col_fields[0][0],None
                retval.append([afield2,ufield2,ifield2])
        testtimer.end()
        return retval
        
#if True in fields_is_numfield[1:-1]:
            # then there is a chance that we've got 2 columns...

    def find_unit_field (self, fields, fields_is_numfield):
        testtimer = TimeAction('mealmaster_importer.find_unit_field',10)
        if 0 < fields[0][1]-fields[0][0] <= self.unit_length and len(fields)>1:
            testtimer.end()
            return fields[0]
        testtimer.end()

        
    def find_amt_field (self, fields, fields_is_numfield):
        testtimer = TimeAction('mealmaster_importer.find_amt_field',10)
        afield = None
        aindex = None
        for i,f in enumerate(fields):
            if fields_is_numfield[i]:
                if not afield:
                    afield = f
                    aindex = i
                elif i == aindex + 1:
                    afield = [afield[0],f[1]] # give it a new end
                    aindex = i
                else:
                    return aindex,afield
        testtimer.end()
        return aindex, afield

    
    def find_ing_fields_old (self):
        testtimer = TimeAction('mealmaster_importer.find_ing_fields_old',10)
        debug("start find_ing_fields",7)
        all_ings = [i[0] for i in self.ingrs]
        fields = find_fields(all_ings) 
        a = []
        while fields and field_match(all_ings,fields[0],
                                     self.amt_field_matcher):
                                     #"^[0-9- /]+$"):
            a.append(fields[0])
            del fields[0]
        if a:
            a=(a[0][0],a[-1][1]) #a is the range from least to most
        if fields and field_match(all_ings,fields[0],
                                  "^..?$"):
            u=fields[0]
            del fields[0]
        else: u=""
        if fields:
            i=(fields[0][0],fields[-1][1])
        else:
            debug("No items? this seems odd.",0)
            i=""
        debug("Returning fields: %s,%s,%s"%(a,u,i),10)
        testtimer.end()
        return a,u,i

    
    def add_item (self, item):
        testtimer = TimeAction('mealmaster_importer.add_item',10)
        self.ing['item']=item.strip()
        # fixing bug 1061363, potatoes; cut and mashed should become just potatoes
        # for keying purposes
        key_base = self.ing['item'].split(";")[0]
        self.ing['ingkey']=self.km.get_key_fast(key_base)
        testtimer.end()
        
    def parse_inglist(self):
        testtimer = TimeAction('mealmaster_importer.parse_inglis',10)
        debug("start parse_inglist",5)
        """We handle our ingredients after the fact."""
        ingfields =self.find_ing_fields()
        debug("ingredient fields are: %s"%ingfields,10)
        for s,g in self.ingrs:
            for afield,ufield,ifield in ingfields:                
                self.group = g
                amt,u,i = get_fields(s,(afield,ufield,ifield))
                if amt or u or i:
                    self.start_ing()
                    if amt:
                        self.add_amt(amt)
                    if u:
                        self.add_unit(u)
                    optm=self.ing_opt_matcher.match(i)
                    if optm:
                        item=optm.groups()[0]
                        self.ing['optional']='yes'
                    else:
                        item = i
                    self.add_item(item)
                    debug("committing ing: %s"%self.ing,6)
                    self.commit_ing()
                    testtimer.end()
                    
    def add_unit (self, unit):
        testtimer = TimeAction('mealmaster_importer.add_unit',10)
        unit = unit.strip()
        if mmf.unit_conv.has_key(unit):
            unit = mmf.unit_conv[unit]
        importer.importer.add_unit(self,unit)
        testtimer.end()
        
                

def split_fields (strings, char=" "):
    testtimer = TimeAction('mealmaster_importer.split_fields',10)
    debug("start split_fields",10)
    fields=find_fields(strings,char)
    testtimer.end()
    
def fields_match (strings, fields, matcher):
    testtimer = TimeAction('mealmaster_importer.fields_match',10)
    """Return an array of True or False values representing
    whether matcher is a match for each of fields in string."""
    retarray = array.array('H',[1]*len(fields))
    # cycle through each string broken into our fields
    for ff in [[s[f[0]:f[1]] for f in fields] for s in strings]:
        for i,fld in enumerate(ff):
            if fld and retarray[i] and not matcher.match(fld):
                retarray[i]=False
                if not True in retarray: return retarray
    testtimer.end()
    return retarray


def field_match (strings, tup, matcher):
    testtimer = TimeAction('mealmaster_importer.field_match',10)
    debug("start field_match",10)
    if type(matcher)==type(""):
        matcher=re.compile(matcher)
    for f in [s[tup[0]:tup[1]] for s in strings]:
        #f=s[tup[0]:tup[1]]
        if f and not matcher.match(f):
            testtimer.end()
            return False
    testtimer.end()
    return True


def get_fields (string, tuples):
    testtimer = TimeAction('mealmaster_importer.get_fields',10)
    debug("start get_fields",10)
    lst = []
    for t in tuples:
        if t:
            lst.append(string[t[0]:t[1]])
        else:
            lst.append("")
    testtimer.end()
    return lst


def field_width (tuple):
    testtimer = TimeAction('mealmaster_importer.field_width',10)
    debug("start field_width",10)
    if tuple[1]:
        testtimer.end()
        return tuple[1]-tuple[0]
    else:
        testtimer.end()
        return None
    
    
def find_fields (strings, char=" "):
    testtimer = TimeAction('mealmaster_importer.find_fields',10)
    cols = find_columns(strings, char)
    cols.reverse()
    fields = []
    lens = map(len,strings)
    lens.sort()
    end = lens[-1]
    last_col = end
    for col in cols:
        if col == last_col - 1:
            end = col
        else:
            fields.append([col+1,end])
            end = col
        last_col = col
    if end != 0: fields.append([0,end])
    fields.reverse()
    testtimer.end()
    return fields


def find_columns (strings, char=" "):
    testtimer = TimeAction('mealmaster_importer.find_columns',10)
    """Return a list of character indices that match char for each string in strings."""
    debug("start find_columns",10)
    # we start with the columns in the first string
    if not strings:
        return None
    strings=strings[0:]
    strings.sort(lambda x,y: len(x)>len(y))
    columns = [match.start() for match in re.finditer(re.escape(char),strings[0])]
    if len(strings)==1:
        return columns
    # we eliminate all columns that aren't blank for every string
    for s in strings:
        for c in columns[0:]: # we'll be modifying columns
            if c < len(s) and s[c]!=char:
                columns.remove(c)
    columns.sort()
    testtimer.end()
    return columns


        
if __name__ == '__main__':
    import recipeManager, tempfile, sys, profile
    from OptionParser import *
    print 'Testing mealmaster import'
    tmpfile = tempfile.mktemp()
    rd = rmetakit.RecipeManager(tmpfile)
    if not args: args = ['/home/tom/Projects/recipe/Data/200_Recipes.mmf']
    for a in args:
        profile.run("mmf_importer(rd,a,progress=lambda *args: sys.stdout.write('|'),threaded=False)")