mcmerge
=======

This is a tool for stitching together Minecraft maps that have different areas generated by different algorithms causing ugly transitions, for example when using an existing map from Minecraft b1.7 in Minecraft b1.8.

The tool is inspired by the bestofboth script and follows the same basic idea, check it out at:
https://github.com/gmcnew/bestofboth

It also relies on the very excellent pymclevel to do its map editing, you can find it at:
https://github.com/codewarrior0/pymclevel


As with all these sorts of things, use this tool at your own risk. Everything will probably be fine, but if it all goes horribly wrong I can't be held responsible.


How it works
------------

A river is placed at the boundaries between the old and new map areas, and the surrounding valley is smoothed seamlessly together with adjacent chunks. The smoothing is done with a low pass filter that means every chunk will have its own unique appearance.

Two phases are used to perform the work. First the original map is traced with mcmerge to find the contour of the edge of the existing world. Then continue playing on the map (with your new version of Minecraft) to generate additional areas. Finally mcmerge is used to smooth chunks at the boundary between the old and new areas.

I have included some test files in the appropriately named testfiles directory that you can use to run this script on.


Setting up
----------
To use this tool you will first need to install it. There are two available options.


### Binary package
If you're on Windows you can just grab the mcmerge-win32 zip file available on the project download page. Unzip it and you're ready to run.

If you are missing the requisite Microsoft distributable DLL files, mcmerge will fail. Try installing the Microsoft Visual C++ 2008 Redistributable Package (x86) first and you should be good to go. You can get it here:
http://www.microsoft.com/download/en/details.aspx?displaylang=en&id=29


### Script package
On other platforms or if you want to set up the environment your self you will first need to install Python and some libraries. This tool has not been tested with Python 3.0 so Python 2.7 is recommended. You can get the latest version from here:
http://www.python.org/download/

If you're downloading Python for Windows, it is recommended you install the plain version rather than the X86-64 version as some of the libraries required only come precompiled in 32-bit versions.


Once you have Python installed you will need to install the NumPy and SciPy library. You can find the download links at:
http://new.scipy.org/download.html

You will also need to install PyYAML which can be found here:
http://pyyaml.org/wiki/PyYAML

Both NumPy and SciPy have pre-built installable packages for Windows and OS X on the SourceForge pages linked from the above page. Grab the latest version and you're ready to go. PyYAML also provides a Windows installer but should be quite easy to install from the command line on other operating systems.

Finally, if you're on Windows, you should install the python win32 extension. The utility seems to work OK without it but warning messages are displayed and there's no guarantee things will keep working in the future. You can find the download on the project page here:
http://sourceforge.net/projects/pywin32/


Merging your world
------------------

Once you have the required bits installed, you can download this tool then fire up the command line and cd over to the location of the script. Then follow these steps:

1.  Backup your world directory. If you or the tool breaks something you'll be able to recover. You can find your singleplayer maps in the following locations (keep the quotation marks if you're not sure):

        - Windows: "%AppData%\.minecraft\saves"
        - Linux: "$HOME/.minecraft/saves"
        - OS X: "$HOME/Library/Application Support/minecraft/saves"

2.  Adjust sea height. This step is optional but highly recommended if merging a map from a version of Minecraft before b1.8. The sea has been moved down by 1 block in Minecraft b1.8 and it is recommended you adjust the map accordingly. Run the following command to mark which blocks will be shifted (make sure you have the correct world name):

        python mcmerge.py shift "%AppData%\.minecraft\saves\World"

    NOTE: If you experience any problems with this method you can still do this with MCEdit; nudge the whole world down by one block but make sure you leave the lower most block level intact so you still have a solid bedrock.

3.  Run the contour trace phase on the map, for example (use the correct world name for you):

        python mcmerge.py trace "%AppData%\.minecraft\saves\World"

    This places the file contour.dat in the world directory which will be read when merging.

4.  Play some Minecraft to generate the new areas bordering with your old map.

5.  Run the merging phase. You can tweak various parameters for the best look. Using the default configuration this will look something like the following (again, make sure you specify the correct world directory):

        python mcmerge.py merge "%AppData%\.minecraft\saves\World"

6.  Get back into the game and watch the floating debris disappear.

You can repeat steps 4 - 6 as many times as you need as the tool will keep track of which border areas haven't yet been merged because they haven't had new areas generated next to them.

NOTE: For Windows users using the packaged binary, replace 'python mcmerge.py' with 'mcmerge.exe' in the above commands.


Configuration
-------------

To see what commands are available in the tool, type: <code>python mcmerge.py help</code>

You can access the options available for each command with: <code>python mcmerge.py help &lt;command_name&gt;</code>

NOTE: With the win32 executable you would just type: <code>mcmerge help</code>

Below are a few comments about the various commands that may be useful.

### *Common*
Several commands share some options. The name of the contour file found in the world directory may be specified with the --contour option. Contour files are allowed to be built up in several steps, however it is possible to clear all previous data and start fresh by using the --reset option. Finally, commands that manipulate chunks will finish up by relighting them, this step can be skipped for speed by using --no-relight but it may leave some dark spots.

### shift
Shifting is not normally done immediately but the chunks to shift are instead marked in the contour file, and only applied with the 'merge' command. However, it is possible to force shifting right away with the --immediate option. You can alter by how many blocks the chunks are shifted up or down by giving a number to the --up or --down options respectively.

### relight
This is simply used to relight all chunks and does nothing else.

### trace
The contour may be built up in multiple steps, however this is quite involved and for most usage scenarios it is recommended to simply use the default setup which will mark out a river around the edge of the world. For more complicated contours additional options are available, however since this is done with the command line, it is not an ideal interface. A description of the contour data file is also available in the CONTOUR.md file, should anyone wish to build a better GUI tool to perform this tracing more intuitively.

For advanced usage the way the contour is built up may be understood by breaking it up into several steps. The key to keep in mind here is that first the new edge is traced out and trimmed by comparing it to already existing edge data in the contour file, and then the resulting new edge data formed in this way is added to the contour file that already exists.

1. First the type of merging to be performed with the edge about to be traced is specified. Note that the 'ocean' type isn't a type on its own but rather specifies whether terrain removed below sea level should be filled with water instead of air, in association with other merge types.
2. The chunks defining both sides of the desired edge are selected. These may be either:
   * union        - chunks from both the existing and new edge being added
   * intersection - only chunks present in both the existing and the new edge
   * difference   - only chunks present in the new edge but not the old one
   * missing      - selects every chunk from the old edge in the same location wherever a chunk is missing in the provided world
3. Once the chunks defining the edge have been selected, the type of merge (as specified in step #1) will be applied to those edges chunks. Again, this is one of:
   * add          - both the merge type from the existing and the new edge are used
   * replace      - for the chunks from the new edge, only use the new merge type
   * transition   - this is mostly like 'replace' however it attempts to perform an 'add' on the chunks
                    where the old and new edges meet and does some additional smoothing for a nice
                    transition between the two
4. Finally once the new edge is fully defined with steps 1-3, it is either added to the contour data along with the old data using --combine, or it replaces the old data entirely by using --discard.

NOTE: All these option values may be abbreviated by using only the leading letters (or even letter).

### merge
There are two filters available that may be specified with --filter (or individually with --filter-river and --filter-even), there is 'smooth' and 'gauss'. The 'smooth' filter is the default (it's a perfect frequency filter). The gaussian filter gives more regular results and can perform much stronger smoothing, however it also tends to give more boring looking results.

You can also fiddle with how wide the river and the valley the river flows through are, the height of the river and the height of the river bank (specified with --valley-height), and the sea level at which water will be placed. There are options to control how the river weaves. There's also an option for how much the river and valley should be narrowed when a river flows on both sides of a chunk. Finally, the --cover-depth option specifies the depth of blocks that are taken from the surface of the unmerged areas and used as the new surface for the carved out valley.

While the merge command will by default perform both shifting and merging operations, either one of these can be skipped with the --no-shift and --no-merge options respectively.

Happy merging!


Advanced tracing examples
-------------------------

Here are some examples of how the more advanced tracing features can be used in practice. Most people can skip this section entirely. I will attempt to provide illustrations to clarify this slightly. The illustrations will map one chunk to one character according to the below legend:

        Tracing illustration legend

        # - normal existing chunk   * - no chunk generated yet
        X - edge side A (capital)   x - edge side B (lower case)
        R - marked for river merge  E - marked for even merge
        B - both river and even     C - marked for even and ocean
        W - water/ocean chunk

### River trace with evened intervals

* This example starts with a trimmed map [1].

* We proceed to do a simple river merge around the outside of the map [2].

        python mcmerge.py trace -r -t river <world>

* So far we have:

        1.                      2.
        #########*********      ########Rr********
        #########*********      ########Rrrr******
        ###########*******      ########RRRr******
        ###########*******      ##########Rr******
        ###########*******      ##########Rr******
        ###########*******      ##########Rr******
        ###########*******      ##########Rr******
        ###########*******      ##########Rr******

* We then wish to make a section of the edge be evened out without a river.

* We first need a fully fleshed out map so we have somewhere to cut things out to specify additional edges. So we load out Minecraft and generate the missing chunks [3].

* After this we cut out the part we want to be evened out instead, we remove all the chunks that will contain the edge with the new merge method [4a].

        3a.                     4a.
        ########Rr########      ########Rr########
        ########Rrrr######      ########Rrrr######
        ########RRRr######      ########RRRr######
        ##########Rr######      ##########Rr######
        ##########Rr######      #######********###
        ##########Rr######      #######********###
        ##########Rr######      #######********###
        ##########Rr######      ##########Rr######

* Now we are ready to run the next trace step. We tell the tracer to form an edge from the intersection of the old edge and the missing chunks. We also use the join the merge types with 'transition' so we seamlessly go from a river to evened ground to a river again.

        python mcmerge.py trace -t even -s missing -j tran -b <world>

* This gives us our final result [6a] ready to have the missing chunks generated and then be merged with the 'merge' command.

        6a.
        ########Rr########
        ########Rrrr######
        ########RRRr######
        ##########Bb######
        #######***Ee***###
        #######***Ee***###
        #######***Ee***###
        ##########Bb######

### River trace with evened intervals using set operations

* This is much like the above method but we use the set operation selection type instead. In the step where we perform the specific cutout and perform the trace as follows.

* We cut out the part we want to be evened out, remember, only the location where the cut out meets the existing edge matters since we will user their intersection [4b].

        3b.                     4b.
        ########Rr########      ########Rr########
        ########Rrrr######      ########Rrrr######
        ########RRRr######      ########RRRr######
        ##########Rr######      ##########Rr######
        ##########Rr######      ##########R*****##
        ##########Rr######      ##########R*****##
        ##########Rr######      ##########R*****##
        ##########Rr######      ##########Rr######

* Now we are ready to run the next trace step. We select only the intersection between the old edge, and the new edge that will be generated around our newly cut out section. We also use the join the merge types with 'transition' so we seamlessly go from a river to evened ground to a river again.

        python mcmerge.py trace -t even -s intersect -j tran -b <world>

* This gives us our final result [6b] ready to have the missing chunks generated and then be merged with the 'merge' command.

        6b.
        ########Rr########
        ########Rrrr######
        ########RRRr######
        ##########Bb######
        ##########Ee****##
        ##########Ee****##
        ##########Ee****##
        ##########Bb######

### Evened edge on ocean coastline

* In this example we have trimmed map [1] and when we generate the missing chunks in Minecraft we see that they are all ocean [2].

        1.                      2.
        #########*********      #########WWWWWWWWW
        #########*********      #########WWWWWWWWW
        ###########*******      ###########WWWWWWW
        ###########*******      ###########WWWWWWW
        ###########*******      ###########WWWWWWW
        #############*****      #############WWWWW
        ##################      ##################
        ##################      ##################

* Starting with the map in [1] we run a trace command specifying we wish to even out the edge and that we want the border to be filled with ocean water:

        python mcmerge.py trace -r -t even -t ocean <world>

* This gives us the result in [3], ready to have the missing chunks generated and and then be merged with the 'merge' command.

        3.
        ########Oo********
        ########Oooo******
        ########OOOo******
        ##########Oo******
        ##########Oooo****
        ##########OOOooooo
        ############OOOOOO
        ##################


Revision history
----------------

### v0.1
- Initial version
- Places a river at old/new chunk interface and smooths with low pass filter

### v0.2
- Fixed --help switch so works without supplying world
- Modified sea level to be b1.8 compatible and added extra step to fix sea level disconnect
- Ice is no longer treated as terrain to place river in
- Updated to latest version of pymclevel; better support for b1.8 blocks
- River corners now look rounder
- Fixed exception with very wide valley/river values
- Instead of exposed stone being transformed to dirt, the whole top layer is now shifted down; new switch controlling depth of this layer added
- Added win32 executable

### v0.3
- Random river weaving so rivers along straight segments don't look so artificial
- The SciPy library is no longer optional (for anyone using the script version)
- Updated pymclevel and added support for merging with 1.9pre blocks

### v0.4
- Removed floating trees are now replanted with an appropriate sapling
- Added a relighting step so there are no more dark areas under overhangs (no longer need postprocessing with MCMerge)
- Added a new phase for shifting the sea-height (no longer require MCMerge for this)

### v0.4.1
- Updated pymclevel and added support for merging with version 1.0 blocks

### v0.5.0
- Fixed crash when generating rivers in shallows
- Fixed shift mode so that player and spawn location are also shifted
- Modes are no longer specified by options but by a new mandatory parameter
- Added new mode 'relight' that does not alter the world but simply relights all chunks
- Made trace mode considerably more efficient

### v0.5.1
- Fixed packaging to include data and submodule files in new pymclevel
- Made trace mode considerably more efficient (for real this time)

### v0.5.2
- Fixed rare crash when placing river water

### v0.5.3
- Added support for Anvil map format

### v0.6.0
- Reorganised the command line interface for completely independent commands, much easier to find and use options
- New contour file format giving expanded merging abilities
- New merge mode to even out terrain topography without a river
- New merge mode allowing removed blocks below sea level to be replaced with water instead of air, i.e. water spills over onto coast
- Block shifting now delayed until merging step by default, i.e. possible to shift even after new chunks are generated
- New tracing options allowing different merge modes to be specified as well as advanced options to permit transitions between modes
- Better merging performance
- Fixed bug where water one block above sea level would not be removed while erroding terrain
- Fixed crash when empty contour data file was given
- The Win32 executable can now be run from any working directory

### v0.6.1
- Updated pymclevel for better Minecraft 1.3 support
- Algorithm recognises more blocks correctly (e.g. jungle trees)

### v0.6.2
- Updated pymclevel for better Minecraft 1.4 support
- Currently only Anvil map format supported for PC (convert older maps with Minecraft first or use v0.6.1)

### v0.6.3
- Updated pymclevel for better Minecraft 1.5 support
- Older maps (before Minecraft 1.2 Anvil format) still require conversion using Minecraft first
