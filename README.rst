A Docbook parser for docutils and Sphinx
========================================

This project provides a simple Docbook converter for use with docutils and
sphinx.  When used with Sphinx, it can read docbook assembly files to produce
toctrees automatically, or it can be used to incorporate individual docbook
files in documentation (together with rST toctree).

Assembly handling is designed to work with the ``topic-maker-chunk.xsl`` style
from the Docbook distribution:
::

   xsltproc --xinclude \
      --stringparam chunk.section.depth 1  \
      --stringparam assembly.filename index.xml \
      --stringparam base.dir topics/ \
      /usr/share/sgml/docbook/xsl-ns-stylesheets-1.79.1/assembly/topic-maker-chunk.xsl -

