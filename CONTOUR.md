Contour data file
=================

Below is a description of the contour file syntax for anyone who would like to modify it directly. The contour file is saved in the directory of the Minecraft map to which it refers. Note that release v0.6 changed the contour data file format and it is this format which is described here. However, mcmerge will still understand the old format in case you have maps where the merging wasn't completed.

I'll use BNF notation to draw up the syntax with some explanations in between. Note that literal tokens are enclosed by "" for strings and // for regexs. Also because I'm lazy I use the shorthand _<a: b>_ to mean _<a> where <a> ::= <b>_.

Overview
--------

The file consist of two sections:

    <contour_file> ::= <header> <data>

Some general tokens used throughout:

    <EOL> ::= "\n"
    <SPACE> ::= /[ \t]+/

Header
------

The file always begins with a header specifying the format version:

    <header> ::= "VERSION " <version_string> <EOL>

Data
----

The data consist of lines, one line per chunk. Each chunk is identified by its coordinates, specifying the sides of the chunk which form the outer edge, and the actions to be performed while merging. The merging actions include shifting blocks up/down and merging methods applied to merge with neighbouring chunks.

    <data> ::= <data_line>*
    
    <data_line> ::= [<SPACE>] <coordinates>
                    <SPACE> <shift_data>
                    <SPACE> <merge_data>
                    <EOL>

    <coordinates> ::= <x_coordinate: INTEGER> <SPACE> <z_coordinate: INTEGER>

For <shift_data> and <merge_data>, the absence of any data is indicated with a "-".

    <shift_data> ::= "-" | <shift_down: INTEGER>

    <merge_data> ::= "-" | (<merge_methods> <SPACE> <edge_definition>)
    <merge_methods> ::= <merge_method>+

The <merge_method> value is one of the tokens as per the below table:

     token  |  meaning
    --------+-----------------------
      "E"   |  even out the terrain between chunks
      "R"   |  place a river and valley between chunks
      "O"   |  all removed terrain below sea level is replaced with
            |    water rather than air
      "T"   |  tidy up, even out terrain once all other merges are
            |    done to allow smooth transitions

Finally the edge direction is specified as follow:

    <edge_definition> ::= [<edge_direction> <SPACE>] <edge_direction>
    <edge_direction> ::= "N" | "NE" | "E" | "SE" | "S" | "SW" | "W" | "NW"

The edge directions correspond to the cardinal points of the compass.

Error handling
--------------

No syntax error handling is implemented at the moment.

