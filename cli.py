import sys, os.path, getopt
import carve, contour, filter, various, merge

# Static constants
version = '0.6.1'

# Define option defaults
contour_file_name = 'contour.dat'
contour_reset = False
contour_select = 'union'
contour_join = 'replace'
contour_combine = False
merge_types = ['river']
merge_no_shift = False
merge_no_merge = False
shift_down = 1
shift_immediate = False
world_dir = None

# Validate them
assert all(x in contour.Contour.methods for x in merge_types)
assert contour_select in contour.Contour.SelectOperation
assert contour_join in contour.Contour.JoinMethod

# Useful values
program_name = os.path.basename(sys.argv[0])

# Classes to manage commands
class CommandParsingError(Exception):
    pass

class Command(object):
    name = None
    
    short_opts = ""
    long_opts = []
    
    def usage(self):
        """ Display usage of command """
        
        raise NotImplementedError
    
    def parse(self, opts, args):
        """ Propagate the options and arguments given """
        
        raise NotImplementedError

# External interface
command_list = []
command_dict = {}

def _complete(options, name):
    """ Complete name out of a list of options """
    
    found = None
    for n in options:
        if n is None:
            continue
        
        if n.startswith(name.lower()):
            if found is None:
                found = n
            else:
                KeyError("ambiguous name")
                
    return found

def complete(name):
    """
    Find full command name corresponding to the given abbreviation.
    May raise KeyError if abbreviation is ambiguous.
    """
    
    try:
        return _complete(command_list, name)
    except KeyError:
        KeyError("ambiguous command name '%s', please provide full name" % args[0])
    
def parse(argv):
    """
    Parse command line options. Returns the name of the command
    and any additional data returned by the command parser.
    
    May raise CommandParsingError if there are problems.
    """
    
    # Find the command
    if len(argv) < 1:
        full = None
        cmd = command_dict[None]
    else:
        try:
            full = complete(argv[0])
        except KeyError, e:
            raise CommandParsingError(str(e))
        
        if full is not None and full in command_dict:
            cmd = command_dict[full]
            argv = argv[1:]
        else:
            cmd = command_dict[None]
            try:
                return None, cmd.parse(*getopt.gnu_getopt(argv, cmd.short_opts, cmd.long_opts))
            except getopt.GetoptError, e:
                raise CommandParsingError("unrecognised command '%s'" % argv[0])
            
    # Process arguments
    try:
        return full, cmd.parse(*getopt.gnu_getopt(argv, cmd.short_opts, cmd.long_opts))
    except getopt.GetoptError, e:
        raise CommandParsingError(str(e))

# Various command helpers
def error(msg):
    print "For usage type: %s help" % os.path.basename(sys.argv[0])
    print
    print "Error: %s" % msg
    sys.exit(1)
    
def _do_help(cmd, opts, small_opt=False):
    matching = ('-h', '--help') if small_opt else ('--help',)
    if any(opt in matching for opt, _ in opts):
        cmd.usage()
        sys.exit(0)
        
def _get_world_dir(args):
    if len(args) < 1:
        error("must provide world directory location")
    elif len(args) > 1:
        error("only one world location may be specified")
    else:
        return args[0]

def _get_int(raw, name):
    try:
        return int(raw)
    except ValueError:
        error('%s must be an integer value' % name)

def _get_float(raw, name):
    try:
        return float(raw)
    except ValueError:
        error('%s must be a floating point number' % name)

def _get_ints(raw, name, count):
    try:
        ints = tuple(int(x) for x in raw.split(','))
        if len(ints) != count:
            raise ValueError
        return ints
    except ValueError:
        error('%s must be %d comma separated integers' % (name, count))

# Define command behaviour
def __add_command(cmd):
    """ Add a new command to the existing list """
    
    command_list.append(cmd.name)
    command_dict[cmd.name] = cmd()
    return cmd

@__add_command
class BaseCommand(Command):
    name = None
    
    short_opts = "h"
    long_opts = ['help', 'version']
    
    def usage(self):
        print "Usage: %s <cmd> [options] [arguments] ..." % program_name
        print
        print "Stitches together existing Minecraft map regions with newly generated areas"
        print "by separating them with a river."
        print
        print "Basic use employs a multi phase process. First trace the contour outline with"
        print "the 'trace' command, then generate new areas with Minecraft, finally merge the"
        print "old and new with the 'merge' command. Other options are also available."
        print
        print "Commands:"
        print "  help           display information about specified command"
        print "  shift          shifts the map height up or down, for example, this is useful"
        print "                 to match sea level heights between version b1.7 and b1.8"
        print "  trace          generates contour data for the original world before"
        print "                 new areas are added"
        print "  merge          merges and smooths the old and new areas together using the"
        print "                 data collected in the trace phase"
        print "  relight        relights all chunks in the world without doing anything"
        print "                 else, note that other modes do this automatically"
        print 
        print "Options:"
        print "-h, --help                    displays this help"
        print "    --version                 prints the version number"
        
    def parse(self, opts, args):
        global version
        
        _do_help(self, opts, True)
        if any(opt in ('--version',) for opt, _ in opts):
            print "mcmerge v%s" % version
            sys.exit(0)
            
@__add_command
class HelpCommand(Command):
    name = "help"
    
    short_opts = "h"
    long_opts = ['help']
    
    def usage(self):
        print "Usage: %s %s [command]" % (program_name, self.name)
        print
        print "Displays information about the given command, or this help if no command was"
        print "specified."
        print 
        print "Options:"
        print "-h, --help                    displays this help"
        
    def parse(self, opts, args):
        _do_help(self, opts, True)
        if len(args) < 1:
            command_dict[None].usage()
            sys.exit(0)
            
        try:
            full = complete(args[0])
        except KeyError, e:
            error(str(e))
            
        if full is None:
            error("unknown command '%s' specified" % args[0])
        else:
            command_dict[full].usage()
            sys.exit(0)
            
        return {}
            
@__add_command
class ShiftCommand(Command):
    name = "shift"
    
    short_opts = "d:u:irc:"
    long_opts = ['help', 'down=', 'up=', 'immediate', 'reset', 'contour=', 'no-relight']
    
    def usage(self):
        print "Usage: %s %s <world_dir>" % (program_name, self.name)
        print
        print "This command specifies how to shift the sea-level of the map in the contour"
        print "file. The actual shifting will take place when the 'merge' command is run."
        print "This should only be necessary when moving between version b1.7 (or earlier)"
        print "to verion b1.8 (or later) maps."
        print 
        print "Options:"
        print "-d  --down=<val>              number of blocks to shift the map down by (may"
        print "                              be negative), default: %d" % shift_down
        print "-u  --up=<val>                number of blocks to shift the map up by (may"
        print "                              be negative), default: %d" % -shift_down
        print "-i  --immediate               perform shifting immediately rather than simply"
        print "                              marking what should be shifted"
        print
        print "Common options:"
        print "-r, --reset                   reset pre-existing contour file"
        print "-c, --contour=<file_name>     contour file recording the shift data in the"
        print "                              world directory, default: %s" % contour_file_name
        print "    --no-relight              don't do relighting, this is faster but leaves"
        print "                              dark areas"
        
    def parse(self, opts, args):
        global world_dir, shift_down, shift_immediate, contour_file_name, contour_reset
        
        _do_help(self, opts)
        world_dir = _get_world_dir(args)
    
        for opt, arg in opts:
            if opt in ('-d', '--down'):
                shift_down = _get_int(arg, 'shift down')
            elif opt in ('-u', '--up'):
                shift_down = -_get_int(arg, 'shift up')
            elif opt in ('-i', '--immediate'):
                shift_immediate = True
            elif opt in ('-r', '--reset'):
                contour_reset = True
            elif opt in ('-c', '--contour'):
                contour_file_name = arg
            elif opt == '--no-relight':
                various.Shifter.relight = False
                merge.Merger.relight = False
            
@__add_command
class RelightCommand(Command):
    name = "relight"
    
    short_opts = ""
    long_opts = ['help']
    
    def usage(self):
        print "Usage: %s %s <world_dir>" % (program_name, self.name)
        print
        print "Relights all the chunks in the world without doing anything else."
        print "Note that some of the other commands do this automatically."
        
    def parse(self, opts, args):
        global world_dir
        
        _do_help(self, opts)
        world_dir = _get_world_dir(args)
            
@__add_command
class TraceCommand(Command):
    name = "trace"
    
    short_opts = "t:s:j:bdrc:"
    long_opts = ['help', 'reset', 'contour=']
    
    def usage(self):
        print "Usage: %s %s <world_dir>" % (program_name, self.name)
        print
        print "Generates a contour data file specifying the edge of the original world"
        print "before new areas are added."
        print
        print "Additional data may be added to the initial edge contour. The new edge"
        print "is first selected by performing the specified set operation. Using the"
        print "specified new merge type, the merge types in old and new data sets are"
        print "then combined using the given joining method. Finally old and new data"
        print "is either combined together or the old data is completely discarded."
        print
        print "Options:"
        print "-t, --type=<val>              type of merge between traced edge chunks"
        print "                              one of:"
        print "                                even       - connect both sides without river"
        print "                                river      - place river between boths sides"
        print "                                ocean      - add ocean below sea level when"
        print "                                             using 'even'"
        print "                              multiple may be specified (default: %s)" % ', '.join(merge_types)
        print "-s, --select=<operation>      new edge will be formed by combining with old"
        print "                              edge set using one of:"
        print "                                union      - edge chunks from either"
        print "                                intersect  - edge chunks only in both"
        print "                                difference - edge chunks in new but not old"
        print "                              or select which old edge chunks will be present"
        print "                              in the new edge directly:"
        print "                                missing    - all edge chunks where chunks are"
        print "                                             missing in the current world map"
        print "                              (default: %s)" % contour_select
        print "-j, --join=<method>           join old and new merge type using one of:"
        print "                                add        - both merge types"
        print "                                replace    - only use new merge type"
        print "                                transition - use both at exterior meeting"
        print "                                             point but only new for the rest"
        print "                              (default: %s)" % contour_join
        print "-b, --combine                 combine new and existing data together"
        print "-d, --discard                 retain new data and discard old (default)"
        print 
        print "Common options:"
        print "-r, --reset                   reset pre-existing contour file"
        print "-c, --contour=<file_name>     file that records the contour data in the"
        print "                              world directory, default: %s" % contour_file_name
        
    def parse(self, opts, args):
        global world_dir, merge_types, contour_select, contour_join, contour_combine, contour_reset, contour_file_name
        
        _do_help(self, opts)
        world_dir = _get_world_dir(args)
    
        if any(opt in ('-t', '--type') for opt, _ in opts):
            merge_types = []
            
        for opt, arg in opts:
            if opt in ('-t', '--type'):
                try:
                    merge_type = _complete(contour.Contour.methods.iterkeys(), arg)
                except KeyError:
                    error("ambigous type value '%s'" % arg)
                    
                if merge_type is None:
                    error("unknown type '%s' requested" % arg)
                else:
                    merge_types.append(merge_type)
            elif opt in ('-s', '--select'):
                try:
                    contour_select = _complete([str(x) for x in contour.Contour.SelectOperation], arg)
                except KeyError:
                    error("ambigous select value '%s'" % arg)
                if contour_select is None:
                    error("unknown select value '%s' requested" % arg)
            elif opt in ('-j', '--join'):
                try:
                    contour_join = _complete([str(x) for x in contour.Contour.JoinMethod], arg)
                except KeyError:
                    error("ambigous join value '%s'" % arg)
                if contour_join is None:
                    error("unknown join value '%s' requested" % arg)
            elif opt in ('-b', '--combine'):
                contour_combine = True
            elif opt in ('-d', '--discard'):
                contour_combine = False
            elif opt in ('-r', '--reset'):
                contour_reset = True
            elif opt in ('-c', '--contour'):
                contour_file_name = arg

@__add_command
class MergeCommand(Command):
    name = "merge"
    
    short_opts = "s:f:c:d:r:v:"
    long_opts = ['help', 'smooth-factor=', 'factor-river=', 'factor-even=',
                 'filter=', 'filter-river=', 'filter-even=', 'river-width=',
                 'valley-width=', 'river-height=', 'valley-height=',
                 'river-centre-deviation=', 'river-width-deviation=',
                 'river-centre-bend=', 'river-width-bend=',
                 'sea-level=', 'narrow-factor=',
                 'no-shift', 'no-merge', 'cover-depth=',
                 'contour=', 'no-relight']
    
    def usage(self):
        print "Usage: %s %s <world_dir>" % (program_name, self.name)
        print
        print "Merges and smooths the old and new areas together according to the"
        print "contour file. The contour file must first be generated using other"
        print "commands."
        print 
        print "Options:"
        print "-s, --smooth-factor=<factor>  smoothing filter factor for all cases"
        print "    --factor-river=<factor>   river smoothing factor, default: %.2f" % merge.ChunkShaper.filt_factor_river
        print "    --factor-even=<factor>    even smoothing factor, default: %.2f" % merge.ChunkShaper.filt_factor_even
        print "-f, --filter=<filter>         name of filter to use in all cases"
        print "    --filter-river=<filter>   river filter to use, default: %s" % merge.ChunkShaper.filt_name_river
        print "    --filter-even=<filter>    even filter to use, default: %s" % merge.ChunkShaper.filt_name_even
        print "                              available: %s" % ', '.join(filter.filters.iterkeys())
        print "    --cover-depth=<val>       depth of blocks transferred from original surface"
        print "                              to carved out valley bottom, default: %d" % merge.ChunkShaper.shift_depth
        print "    --sea-level=<val>         y co-ord of sea level, default: %d" % merge.ChunkShaper.sea_level
        print
        print "-r, --river-width=<val>       width of the river, default: %d" % (merge.ChunkShaper.river_width*2)
        print "-v, --valley-width=<val>      width of the valley, default: %d" % (merge.ChunkShaper.valley_width*2)
        print "    --river-height=<val>      y co-ord of river bottom, default: %d" % merge.ChunkShaper.river_height
        print "    --valley-height=<val>     y co-ord of valley bottom, default: %d" % merge.ChunkShaper.valey_height
        print "    --river-centre-deviation=<low>,<high>"
        print "                              lower and upper bound on river centre"
        print "                              deviation, default: %d,%d" % carve.river_deviation_centre
        print "    --river-width-deviation=<low>,<high>"
        print "                              lower and upper bound on river width"
        print "                              deviation, devault: %d,%d" % carve.river_deviation_width
        print "    --river-centre-bend=<dst> distance between river centre bends"
        print "                              default: %.1f" % carve.river_frequency_centre
        print "    --river-width-bend=<dst>  distance between river width bends"
        print "                              default: %.1f" % carve.river_frequency_width
        print "    --narrow-factor=<val>     amount to narrow river/valley when found on"
        print "                              both sides of a chunk, default: %.2f" % carve.narrowing_factor
        print
        print "    --no-shift                don't perform shifting operations"
        print "    --no-merge                don't perform merging operations"
        print
        print "Common options:"
        print "-c, --contour=<file_name>     file that records the contour data in the"
        print "                              world directory, default: %s" % contour_file_name
        print "    --no-relight              don't do relighting, this is faster but leaves"
        print "                              dark areas"
        
    def parse(self, opts, args):
        global world_dir, contour_file_name
        global merge_no_shift, merge_no_merge
        
        _do_help(self, opts)
        world_dir = _get_world_dir(args)
    
        for opt, arg in opts:
            if opt in ('-s', '--smooth-factor'):
                merge.ChunkShaper.filt_factor_river = \
                merge.ChunkShaper.filt_factor_even = \
                    _get_float(arg, 'smoothing filter factor')
            elif opt == '--factor-river':
                merge.ChunkShaper.filt_factor_river = _get_float(arg, 'river smoothing filter factor')
            elif opt == '--factor-even':
                merge.ChunkShaper.filt_factor_even = _get_float(arg, 'even smoothing filter factor')
            elif opt in ('-f', '--filter'):
                if arg in filter.filters:
                    merge.ChunkShaper.filt_name_river = merge.ChunkShaper.filt_name_even = arg
                else:
                    error('filter must be one of: %s' % ', '.join(filter.filters.iterkeys()))
            elif opt in ('--filter-river'):
                if arg in filter.filters:
                    merge.ChunkShaper.filt_name_river = arg
                else:
                    error('filter must be one of: %s' % ', '.join(filter.filters.iterkeys()))
            elif opt == '--filter-even':
                if arg in filter.filters:
                    merge.ChunkShaper.filt_name_even = arg
                else:
                    error('filter must be one of: %s' % ', '.join(filter.filters.iterkeys()))
            elif opt == '--sea-level':
                merge.ChunkShaper.sea_level = _get_int(arg, 'sea level')
            elif opt == '--cover-depth':
                cover_depth = _get_int(arg, 'cover depth')
                if cover_depth < 0:
                    cover_depth = 0
                merge.ChunkShaper.shift_depth = cover_depth
            elif opt in ('-r', '--river-width'):
                val = _get_int(arg, 'river width')
                merge.ChunkShaper.river_width = val / 2 + val % 2
            elif opt in ('-v', '--valley-width'):
                val = _get_int(arg, 'valley width')
                merge.ChunkShaper.valley_width = val / 2 + val % 2
            elif opt == '--river-height':
                merge.ChunkShaper.river_height = _get_int(arg, 'river height')
            elif opt == '--valley-height':
                merge.ChunkShaper.valey_height = _get_int(arg, 'valley height')
            elif opt == '--river-centre-deviation':
                carve.river_deviation_centre = _get_ints(arg, 'river centre deviation', 2)
            elif opt == '--river-width-deviation':
                carve.river_deviation_width = _get_ints(arg, 'river width deviation', 2)
            elif opt == '--river-centre-bend':
                carve.river_frequency_centre = _get_float(arg, 'river centre bend distance')
            elif opt == '--river-width-bend':
                carve.river_frequency_width = _get_float(arg, 'river width bend distance')
            elif opt == '--narrow-factor':
                carve.narrowing_factor = _get_int(arg, 'narrowing factor')
            elif opt == '--no-shift':
                merge_no_shift = True
            elif opt == '--no-merge':
                merge_no_merge = True
            elif opt in ('-c', '--contour'):
                contour_file_name = arg
            elif opt == '--no-relight':
                various.Shifter.relight = False
                merge.Merger.relight = False

