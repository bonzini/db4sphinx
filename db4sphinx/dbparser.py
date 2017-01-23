# -*- coding: utf-8 -*-
"""
    Simplified DocBook parser for docutils and sphinx
    =================================================
    This script may not work out of the box, but is easy to extend.
    Docbook has >400 elements, only about 100 are supported for now.
    It is more or less limited to the output of makeinfo and kernel-doc.

    :copyright: 2009 Marcin Wojdyr, 2016 Paolo Bonzini
    :license: MIT.
"""

import lxml.etree
from io import BytesIO

import re

import docutils.parsers
from docutils import nodes

__version__ = '0.0.1'
__contributors__ = ('Kurt McKee <contactme@kurtmckee.org>',
                    'Anthony Scopatz <ascopatz@enthought.com>',
                    'Pete Jemian <jemian@anl.gov>',
                    'Paolo Bonzini <pbonzini@redhat.com>',
                   )

# missing: images, bibliography, ...

class DocbookConverter(object):
    ''' converts DocBook tree into docutils nodes '''

    _NSMAP = {}

    def __init__(self, parser, document, ns):
        self.parser = parser        # object that called the converter
        self.document = document
        # to avoid duplicate error reports
        self._not_handled_ns = set()
        self._not_handled_tags = set()
        # delayed output for footnote nodes
        self._save = []
        # currently open elements
        self._stack = []
        # anchors to be attached to the next element
        self._anchors = []
        # function to be called to convert <title>
        self._title_handler = None
        # a function that is used as _text_mangle_fn inside <listitem>
        self._listitem_mangle_fn = None
        # a function that is used to modify the first text node after
        # it is assigned a non-None value
        self._text_mangle_fn = None
        # used to pick arabic numbers vs. lowercase letters
        self._ordered_list_depth = 0
        # maintained for use in rST state machine
        self.current_level = 0

        if ns:
            # DocBook 5
            self._ns = '{http://docbook.org/ns/docbook}'
            self._id_attrib = '{http://www.w3.org/XML/1998/namespace}id'
        else:
            # DocBook 4
            self._ns = ''
            self._id_attrib = 'id'

    def _conv(self, el, parent):
        '''
        Element to string conversion.
        Looks for a defined function e_tag() and calls it,
        where tag is the element name.
        The function e_tag() has one argument,
        the DocBook element node to process.
        '''
        if parent is None:
            parent = self.document

        if isinstance(el, lxml.etree._ProcessingInstruction):
            self.info(el, "ignoring ProcessingInstruction for now")
            return ""
        if isinstance(el, lxml.etree._Comment):
            if el.text.strip():
                self.comment(el, parent)
                return

        tag = str(el.tag)
        method_name = None
        if tag.find(self._ns) == 0:
            # strip off the default namespace
            tag = tag[len(self._ns):]
            method_name = 'e_' + tag
        elif tag.startswith("{"):
            # identify other namespaces by prefix used in XML file
            ns, rawTag = tag[1:].split("}")
            prefix = self._NSMAP.get(ns, None)
            if prefix is None:
                if ns not in self._not_handled_ns:
                    self.warning(el, "Don't know how to handle namespace %s" % ns)
                self._not_handled_tags.add(el.tag)
            else:
                method_name = "e_%s_%s" % (prefix, rawTag)

        self._stack.append(tag)
        if method_name is not None and hasattr(self, method_name):
            getattr(self, method_name)(el, parent)   # call the e_tag(el) method
        else:
            if el.tag not in self._not_handled_tags:
                self.warning(el, "Don't know how to handle <%s>" % el.tag)
                self._not_handled_tags.add(el.tag)
            self.concat(el, parent)
        self._stack.pop()

    def nested_convert(self, el, node):
        self._conv(el, node)

    def convert_root(self, el):
        self._conv(el, self.document)

    def info(self, el, s):
        self.document.reporter.info(s, line=el.sourceline)

    def warning(self, el, s):
        self.document.reporter.warning(s, line=el.sourceline)

    def supports_only(self, el, tags):
        "print warning if there are unexpected children"
        for i in el.getchildren():
            if i.tag not in tags:
                self.warning(el, "%s/%s skipped." % (el.tag, i.tag))

    def what(self, el):
        "returns string describing the element, such as <para> or Comment"
        if isinstance(el.tag, basestring):
            return "<%s>" % el.tag
        elif isinstance(el, lxml.etree._Comment):
            return "Comment"
        else:
            return str(el)

    def has_only_text(self, el, parent):
        "print warning if there are any children"
        if el.getchildren():
            self.warning(el, "children of %s are skipped: %s" % (self.get_path(el, parent),
                      ", ".join(self.what(i) for i in el.getchildren())))

    def has_no_text(self, el, parent):
        "print warning if there is any non-blank text"
        if el.text is not None and not el.text.isspace():
            self.warning(el, "skipping text in <%s>: %s" %
                                  (self.get_path(el, parent), el.text))
            return
        for i in el.getchildren():
            if i.tail is not None and not i.tail.isspace():
                self.warning(el, "skipping text in <%s>: %s" %
                                  (self.get_path(el, parent), i.tail))
            return

    def create_node(self, parent, klass, xml_id=None, ids=None):
        node = klass()
        if xml_id:
            node['ids'] = [xml_id]
        if ids:
            node['ids'] = ids
        if len(self._anchors) > 0:
            node['ids'].append(self._anchors)
            self._anchors = []
        return node

    def node(self, parent, klass, default_klass=nodes.inline,
             xml_id=None, ids=None):
        if xml_id is None and klass is None:
            return parent
        node = self.create_node(parent, (klass or default_klass), xml_id, ids)
        parent += node
        return node

    def create(self, el, parent, klass, default_klass=nodes.inline):
        xml_id = el.get(self._id_attrib) or None
        return self.node(parent, klass, default_klass=default_klass, xml_id=xml_id)

    def concat_into(self, el, parent, need_space=True):
        pending = el.text
        if pending is not None:
            if not need_space:
                pending = pending.lstrip()
        for i in el.getchildren():
            if pending is not None and len(pending):
                parent += self.text(pending)
            pending = None
            self._conv(i, parent)
            if i.tail is not None:
                pending = i.tail
        if pending is not None:
            if not need_space:
                pending = pending.rstrip()
            if len(pending):
                parent += self.text(pending)

    def concat(self, el, parent, klass=None, default_klass=nodes.inline,
               need_space=True):
        """
        concatenate .text with children and their tails
        """
        node = self.create(el, parent, klass, default_klass=default_klass)
        self.concat_into(el, node, need_space)
        return node

    def visit_children(self, el, parent):
        for i in el.getchildren():
            self._conv(i, parent)

    def block(self, el, parent, klass=None):
        node = self.concat(el, parent, klass, default_klass=nodes.compound,
                           need_space=False)
        if len(self._save) == 0:
            return node
        # flush footnotes
        for i in self._save:
            parent += i
        self._save = []
        return node
        
    def inline_text(self, text, parent, inline_class=None, xml_id=None, ids=None):
        node = self.node(parent, nodes.inline, xml_id=xml_id, ids=ids)
        if inline_class is not None:
            node['classes'] = [inline_class]
        node += self.text(text)
        return node

    _GENERIC_DOCROLES = {
        'dfn': nodes.emphasis,
        'kbd': nodes.literal,
    }

    def inline(self, el, parent, inline_class, need_space=True):
        if inline_class in self._GENERIC_DOCROLES:
            klass = self._GENERIC_DOCROLES[inline_class]
            return self.concat(el, parent, klass, need_space=need_space)
        node = self.concat(el, parent, nodes.inline, need_space=need_space)
        node['classes'] = [inline_class]
        return node

    def join_children(self, el, parent, sep, klass=None):
        """
        concatenate .text with children and their tails
        """
        self.has_no_text(el, parent)
        xml_id = el.get(self._id_attrib)
        node = self.node(parent, klass, xml_id=xml_id)
        need_sep = False
        for i in el.getchildren():
            if need_sep:
                node += self.text(sep)
            self._conv(i, node)
            need_sep = True
        return node

    def no_markup_text(self, el, ids=[], need_space=False):
        text = ''
        xml_id = el.get(self._id_attrib)
        if xml_id is not None:
            ids += xml_id
        if el.text is not None:
            text += el.text
            need_space = not el.text[-1].isspace()
        for i in el.getchildren():
            child_text, need_space = self.no_markup_text(i, ids, need_space)
            text += child_text
            if i.tail is not None:
                tail = i.tail
                if not need_space:
                    tail = tail.lstrip()
                if len(tail):
                    text += tail
                    need_space = not tail[-1].isspace()
        return text, need_space

    def no_markup(self, el, parent, klass=nodes.inline):
        ids = []
        text, _ = self.no_markup_text(el, ids, False)
        node = self.node(parent, klass, ids=ids)
        node += self.text(text)
        return node

    def text(self, string):
        if self._text_mangle_fn is not None:
            string = self._text_mangle_fn(string)
            self._text_mangle_fn = None
        return nodes.Text(string)

    def has_any_text(self, el):
        text, _ = self.no_markup_text(el, [], False)
        return len(text.strip()) > 0

    def get_path(self, el, parent):
        t = [el] + list(el.iterancestors())
        return "/".join(str(i.tag) for i in reversed(t))

    def nop(self, el, parent):
        pass

    # Title handling

    @staticmethod
    def rubric(converter, el, parent):
        converter.block(el, parent, nodes.rubric)

    ###################      DocBook elements    #####################

    # special "elements"

    def comment(self, el, parent):
        node = nodes.comment(el.text, el.text)
        parent += node
        return node

    def e_anchor(self, el, parent):
        self._anchors.append(el.get(self._id_attrib))

    # section elements

    def _section(self, el, parent, level):
        def section_title_handler(converter, inner_el, inner_parent):
            #if el.get('label'):
            #    self._text_mangle_fn = lambda x: '%s %s' % (el.get('label'), x)
            converter.block(inner_el, inner_parent, nodes.title)

        save_title_handler = self._title_handler
        self._title_handler = section_title_handler
        node = self.block(el, parent, nodes.section)
        self._title_handler = save_title_handler
        self.document.set_id(node)
        self.current_level = level

    def e_chapter(self, el, parent):
        self._section(el, parent, 0)
    def e_sect1(self, el, parent):
        self._section(el, parent, 1)
    def e_sect2(self, el, parent):
        self._section(el, parent, 2)
    def e_sect3(self, el, parent):
        self._section(el, parent, 3)
    def e_section(self, el, parent):
        self._section(el, parent, self.current_level + 1)
    def e_topic(self, el, parent):
        self._section(el, parent, self.current_level)

    e_preface = e_chapter
    e_appendix = e_chapter

    def e_title(self, el, parent):
        if not self._title_handler is None:
            (self._title_handler)(self, el, parent)

    # top level elements also produce a nodes.section

    e_book = e_chapter
    e_article = e_chapter
    e_topic = e_chapter

    # other block elements

    def e_blockquote(self, el, parent):
        self.block(el, parent, nodes.block_quote)
    def e_epigraph(self, el, parent):
        self.block(el, parent, nodes.epigraph)
    def e_sidebar(self, el, parent):
        save_title_handler = self._title_handler
        self._title_handler = self.rubric
        self.block(el, parent, nodes.sidebar)
        self._title_handler = save_title_handler

    def e_para(self, el, parent):
        self.block(el, parent, nodes.paragraph)
    def e_formalpara(self, el, parent):
        save_title_handler = self._title_handler
        self._title_handler = self.rubric
        self.e_para(el, parent)
        self._title_handler = save_title_handler
    e_simpara = e_para

    def e_note(self, el, parent):
        return self.block(el, parent, nodes.note)
    def e_caution(self, el, parent):
        return self.block(el, parent, nodes.caution)
    def e_important(self, el, parent):
        return self.block(el, parent, nodes.important)
    def e_tip(self, el, parent):
        return self.block(el, parent, nodes.tip)
    def e_warning(self, el, parent):
        return self.block(el, parent, nodes.warning)

    e_informalexample = concat

    def e_literallayout(self, el, parent):
        return self.concat(el, parent, nodes.literal_block)

    e_screen = e_literallayout
    e_programlisting = e_literallayout

    # lists

    def e_glosslist(self, el, parent):
        self.supports_only(el, (self._ns + "glossentry"))
        self.block(el, parent, nodes.definition_list)

    def e_glossentry(self, el, parent):
        self.supports_only(el, (self._ns + "glossterm",
                                 self._ns + "glossdef"))
        self.block(el, parent, nodes.definition_list_item)

    def e_glossterm(self, el, parent):
        self.block(el, parent, nodes.term)

    def e_glossdef(self, el, parent):
        self.block(el, parent, nodes.definition)

    def e_itemizedlist(self, el, parent):
        self.supports_only(el, (self._ns + "listitem"))

        # Texinfo does not use Mark, instead it places the bullet at the
        # beginning of each listitem.  Recover it, and make self._text
        # strip it later.
        item = el.find(self._ns + "listitem[1]/" + self._ns + "para[1]")
        if item is not None and item.text[1] == ' ':
            bullet = item.text[0]
            self._listitem_mangle_fn = lambda s: s[1:].lstrip()
        else:
            bullet = 'bullet'

        node = self.block(el, parent, nodes.bullet_list)
        node['bullet'] = bullet

        # the function can be overwritten - listitem saves/restores it for us
        self._listitem_mangle_fn = None

    def e_orderedlist(self, el, parent):
        self.supports_only(el, (self._ns + "listitem"))
        self._ordered_list_depth = self._ordered_list_depth + 1
        node = self.block(el, parent, nodes.enumerated_list)
        node['enumtype'] = 'arabic' if self._ordered_list_depth == 1 else 'loweralpha'
        node['prefix'] = ''
        node['suffix'] = '.'
        self._ordered_list_depth = self._ordered_list_depth - 1

    def e_listitem(self, el, parent):
        save_listitem_mangle_fn = self._listitem_mangle_fn
        self._text_mangle_fn = self._listitem_mangle_fn
        self._listitem_mangle_fn = None
        self.block(el, parent, nodes.list_item)
        self._listitem_mangle_fn = save_listitem_mangle_fn

    def e_variablelist(self, el, parent):
        #VariableList ::= ((Title,TitleAbbrev?)?, VarListEntry+)
        self.supports_only(el, (self._ns + "varlistentry"))
        self.block(el, parent, nodes.definition_list)

    def e_varlistentry(self, el, parent):
        #VarListEntry ::= (Term+,ListItem)
        self.supports_only(el, (self._ns + "term",
                                 self._ns + "listitem"))
        node = self.create(el, parent, nodes.definition_list_item)
        for term in el.findall(self._ns + "term"):
            self.block(term, node, nodes.term)
        item = el.find(self._ns + "listitem")
        if not (item is None):
            self.block(item, node, nodes.definition)

    # general inline elements

    def e_emphasis(self, el, parent):
        if el.attrib.get('Role', '') == 'strong':
            self.concat(el, parent, nodes.strong)
        else:
            self.concat(el, parent, nodes.emphasis)

    def e_phrase(self, el, parent):
        self.concat(el, parent, nodes.emphasis)
    e_citetitle = e_emphasis
    e_replaceable = e_emphasis

    def e_literal(self, el, parent):
        self.concat(el, parent, nodes.literal)
    e_code = e_literal

    def e_keycap(self, el, parent):
        self.has_only_text(el, parent)
        self.inline(el, parent, 'kbd')

    def e_application(self, el, parent):
        self.has_only_text(el, parent)
        self.inline(el, parent, 'program')

    e_userinput = e_literal
    e_systemitem = e_literal
    e_prompt = e_literal

    def e_filename(self, el, parent):
        self.inline(el, parent, 'file')

    def e_command(self, el, parent):
        self.inline(el, parent, 'command')

    def e_option(self, el, parent):
        self.inline(el, parent, 'option')

    def e_envar(self, el, parent):
        self.inline(el, parent, 'env')

    def e_cmdsynopsis(self, el, parent):
        # just remove all markup and remember to change it manually later
        parent += nodes.comment('cmdsynopsis', 'cmdsynopsis')
        self.no_markup(el, nodes.inline, parent)

    def e_firstterm(self, el, parent):
        self.has_only_text(el, parent)
        self.inline(el, parent, 'dfn')

    def e_userinput(self, el, parent):
        self.inline(el, parent, 'kbd')

    def e_subscript(self, el, parent):
        self.concat(el, parent, nodes.subscript)

    def e_superscript(self, el, parent):
        self.concat(el, parent, nodes.superscript)

    def e_quote(self, el, parent):
        parent += nodes.Text('\u2018', '\u2018')
        node = self.concat(el, parent)
        parent += nodes.Text('\u2019', '\u2019')

    def e_footnote(self, el, parent):
        self.supports_only(el, (self._ns + "para",))
        node = self.node(parent, nodes.footnote_reference)
        node += nodes.Text('#')
        self.document.note_autofootnote_ref(node)

        node = self.create(el, parent, nodes.footnote)
        self.concat_into(el, node, False)
        self.document.note_autofootnote(node)
        self._save.append(node)

    # links

    def e_ulink(self, el, parent):
        node = self.concat(el, parent, nodes.reference)
        node['refuri'] = el.get("url")

    def e_xref(self, el, parent):
        node = self.create(el, parent, nodes.reference)
        if 'linkend' in el.attrib:
            node['refid'] = el.get('linkend')
            node += nodes.Text(node['refid'])
        else:
            node['refuri'] = el.get('{http://www.w3.org/1999/xlink}href')
            node += nodes.Text(node['refuri'])

    def e_link(self, el, parent):
        node = self.concat(el, parent, nodes.reference)
        if 'linkend' in el.attrib:
            node['refid'] = el.get('linkend')
        else:
            node['refuri'] = el.get('{http://www.w3.org/1999/xlink}href')

    # indices

    e_index = nop

    def e_indexterm(self, el, parent):
        '''(http://sphinx.pocoo.org/markup/misc.html#role-index)'''
        self.supports_only(el, (self._ns + 'primary',
                                 self._ns + 'secondary',
                                 self._ns + 'see',
                                 self._ns + 'seealso',))
        ids = []
        if len(el.findall(self._ns + "primary")) == 0:
            self.warning(el, "indexterm has no primary element")
            return

        pri_el = el.find(self._ns + "primary")
        pri, _ = self.no_markup_text(pri_el, ids, False)

        got = False
        for term in ('see', 'seealso',):
            see_el = el.find(self._ns + term)
            if see_el is not None:
                see, _ = self.no_markup_text(see_el, ids)
                self.inline_text('<%s: %s; %s>' % (term, pri, see),
                                  parent, 'index', ids)
        if got:
           return

        sec_el = el.find(self._ns + "secondary")
        if sec_el is not None:
            sec, _ = self.no_markup_text(sec_el, ids)
            pri = '<single: %s; %s>' % (pri, sec)
        if el.attrib.get('significance', "").lower() == "preferred":
            pri = "! " + pri
        self.inline_text(pri, parent, 'index', ids)



    # math and media
    # the DocBook syntax to embed equations is sick.
    # Usually, (inline)equation is
    # a (inline)mediaobject, which is imageobject + textobject

    def e_inlineequation(self, el, parent):
        self.supports_only(el, (self._ns + "mathphrase"))
        self.concat(el, parent)

    def e_equation(self, el, parent):
        self.supports_only(el, (self._ns + "title",
                                 self._ns + "mathphrase"))
        save_title_handler = self._title_handler
        self._title_handler = self.rubric
        self.concat(el, parent)
        self._title_handler = save_title_handler

    def e_mathphrase(self, el, parent):
        if self._stack[-2] == 'inlineequation':
            self.inline(el, parent, 'math', False)
        else:
            self.block(el, parent, nodes.math_block)

    # ignored tags

    e_set = concat
    e_volume = concat
    e_simplesect = concat
    e_info = concat

    # API documentation tags

    # basic programming elements.  a more sophisticated translation is
    # used when additional Sphinx nodes are available

    def e_refentry(self, el, parent):
        self.block(el, parent, nodes.section)

    def e_refsect1(self, el, parent):
        save_title_handler = self._title_handler
        self._title_handler = self.rubric
        node = self.block(el, parent)
        self._title_handler = save_title_handler

    e_info = nop
    e_refentryinfo = nop
    e_refmeta = nop
    e_refnamediv = e_refsect1
    e_refsynopsisdiv = e_refsect1

    def e_refname(self, el, parent):
        self.no_markup(el, parent, nodes.title)

    e_refpurpose = block

    def e_funcprototype(self, el, parent):
        self.supports_only(el, (self._ns + "funcdef",
                                self._ns + "paramdef"))

        funcdef = el.find(self._ns + "funcdef")
        self._conv(funcdef, parent)
        text = "("

        paramdefs = el.findall(self._ns + "paramdef")
        for paramdef in paramdefs:
            parent += self.text(text)
            self._conv(paramdef, parent)
            text = ", "
        parent += self.text(")")

    def e_funcparams(self, el, parent):
        parent += self.text('(')
        # collapse extra spaces, they looks very ugly in sphinx output
        self._text_mangle_fn = lambda x: re.sub(' +', ' ', x)
        node = self.concat(el, parent)
        parent += self.text(')')

    def e_parameter(self, el, parent):
        # collapse extra spaces, they looks very ugly in sphinx output
        self._text_mangle_fn = lambda x: re.sub(' +', ' ', x)
        if self._stack[-2] == 'paramdef':
            self.concat(el, parent, nodes.emphasis)
        else:
            self.concat(el, parent, nodes.literal)

    e_funcsynopsis = block
    e_funcdef = concat
    e_paramdef = concat

    e_manvolnum = e_funcparams
    e_function = e_literal
    e_constant = e_literal
    e_varname = e_literal
    e_structname = e_literal
    e_structfield = e_literal
    e_type = e_literal

class DocbookParser(docutils.parsers.Parser):
    '''
    handle parsing of DocBook source code files
    for Sphinx
    '''

    supported = ('docbook')

    settings_spec = (
        'DocBook Parser Options',
        None,
        (('Expect docbook5 namespace',
          ['--ns'],
          {'action': 'store_true'}),
        ))

    converter = DocbookConverter

    def _parse_xml(self, inputstring):
        # pass an encoding so that lxml doesn't complain about
        # an encoding in the XML processing instruction
        parser = lxml.etree.XMLParser(remove_comments=False, encoding='utf-8')
        input = BytesIO(inputstring.encode('utf-8'))
        tree = lxml.etree.parse(input, parser=parser)
        try:
            # Python 3
            root = tree.getroot()
        except:
            # Python 2
            root = tree

        return root

    def _get_converter(self, document, root):
        return self.converter(self, document, root.tag[0] == '{')

    def parse(self, inputstring, document):
        """Parse `inputstring` and populate `document`, a document tree."""
        self.setup_parse(inputstring, document)
        root = self._parse_xml(inputstring)
        self._get_converter(document, root).convert_root(root)
        self.finish_parse()

    def nested_parse(self, inputstring, state, parent):
        """Parse `inputstring` and populate `document`, a document tree."""
        root = self._parse_xml(inputstring)
        self._get_converter(state.memo.document, root).nested_convert(root, parent)
