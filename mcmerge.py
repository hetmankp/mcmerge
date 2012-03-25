import sys, os.path, errno, logging
import ancillary, cli
from various import Shifter, Relighter
from contour import Contour, ContourLoadError
from merge import ChunkShaper, Merger

logging.basicConfig(format="... %(message)s")
pymclevel_log = logging.getLogger('pymclevel')
pymclevel_log.setLevel(logging.CRITICAL)

if __name__ == '__main__':
    # Values and helpers
    class Modes(object):
       __metaclass__ = ancillary.Enum
       __elements__ = cli.command_list
    
    def error(msg):
        print "Error: %s" % msg
        sys.exit(1)
        
    # Parse command line
    try:
        mode, _ = cli.parse(sys.argv[1:])
    except cli.CommandParsingError, e:
        cli.error(e)
            
    # No command given
    if mode is None:
        cli.error("must specify command")
        
    # Trace contour of the old world
    if mode == Modes.trace:
        print "Finding world contour..."
        contour = Contour()
        try:
            contour.trace_world(cli.world_dir)
        except (EnvironmentError, ContourLoadError), e:
            error('could not read world contour: %s' % e)
        
        print "Recording world contour..."
        try:
            contour.write(os.path.join(cli.world_dir, cli.contour_file_name))
        except EnvironmentError, e:
            error('could not write world contour data: %s' % e)
        
        print "World contour detection complete"
    
    # Shift the map height
    elif mode == Modes.shift:
        print "Loading world..."
        
        try:
            shift = Shifter(cli.world_dir)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Shifting chunks:"
        print
        
        total = sum(1 for _ in shift.level.allChunks)
        width = len(str(total))
        def progress(n):
            print ("... %%%dd/%%d (%%.1f%%%%)" % width) % (n, total, 100.0*n/total)
        shift.log_interval = 200
        shift.log_function = progress
        shifted = shift.shift(-cli.shift_down)
        
        print
        print "Relighting and saving:"
        print
        pymclevel_log.setLevel(logging.INFO)
        try:
            shift.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
        print
        print "Finished shifting, shifted: %d chunks" % shifted

    # Attempt to merge new chunks with old chunks
    elif mode == Modes.merge:
        contour_data_file = os.path.join(cli.world_dir, cli.contour_file_name)
        
        if cli.filt_name == 'gauss':
            if not hasattr(filter, 'scipy'):
                print "You must install SciPy to use this filter"
                sys.exit(1)
        
        print "Getting saved world contour..."
        contour = Contour()
        try:
            contour.read(contour_data_file)
        except (EnvironmentError, ContourLoadError), e:
            if e.errno == errno.ENOENT:
                if os.path.exists(cli.world_dir):
                    error("no contour data to merge with (use trace mode to generate)")
                else:
                    error('could not read world data: File not found: %s' % cli.world_dir)
            else:
                error('could not read contour data: %s' % e)
        
        print "Loading world..."
        print
        
        try:
            merge = Merger(cli.world_dir, cli.filt_name, cli.filt_factor)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Merging chunks:"
        print
        
        total = len(contour.edges)
        width = len(str(total))
        def progress(n):
            print ("... %%%dd/%%d (%%.1f%%%%)" % width) % (n, total, 100.0*n/total)
        merge.log_interval = 10
        merge.log_function = progress
        reshaped = merge.erode(contour)
        
        print
        print "Relighting and saving:"
        print
        pymclevel_log.setLevel(logging.INFO)
        try:
            merge.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
        print
        print "Finished merging, merged: %d/%d chunks" % (len(reshaped), total)
        
        print "Updating contour data..."
        for coord in reshaped:
            del contour.edges[coord]
        
        try:
            if contour.edges:
                contour.write(contour_data_file)
            else:
                os.remove(contour_data_file)
        except EnvironmentError, e:
            error('could not updated world contour data: %s' % e)
            
    # Relight all the chunks on the map
    elif mode == Modes.relight:
        print "Loading world..."
        
        try:
            relight = Relighter(cli.world_dir)
        except EnvironmentError, e:
            error('could not read world data: %s' % e)
        
        print "Marking and relighting chunks:"
        print
        
        pymclevel_log.setLevel(logging.INFO)
        relit = relight.relight()
        
        print
        print "Saving:"
        print
        
        try:
            relight.commit()
        except EnvironmentError, e:
            error('could not save world data: %s' % e)
        pymclevel_log.setLevel(logging.CRITICAL)
        
        print
        print "Finished relighting, relit: %d chunks" % relit
    
    # Should have found the right mode already!
    else:
        error("something went horribly wrong performing mode '%s'" % mode)
