#!/usr/bin/env python
# -*- coding: utf-8 -*-

from docutils.core import publish_cmdline, default_description
from db4sphinx.dbparser import DocbookParser

def db2html():
    description = ('Generates (X)HTML documents from standalone DocBook '
                   'sources.  ' + default_description)

    publish_cmdline(parser=DocbookParser(), writer_name='html', description=description)

def db2odt():
    from docutils.writers import odf_odt
    description = ('Generates ODT documents from standalone DocBook '
                   'sources.  ' + default_description)

    publish_cmdline(parser=DocbookParser(), reader=odf_odt.Reader(), writer=odf_odt.Writer(), description=description)

def db2pseudoxml():
    description = ('Generates pseudo XML documents from standalone DocBook '
                   'sources.  ' + default_description)

    publish_cmdline(parser=DocbookParser(), writer_name='pseudoxml', description=description)

def db2xml():
    description = ('Generates XML documents from standalone DocBook '
                   'sources.  ' + default_description)

    publish_cmdline(parser=DocbookParser(), writer_name='xml', description=description)

