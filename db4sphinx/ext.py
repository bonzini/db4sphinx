# -*- coding: utf-8 -*-
"""
    DocBook extension for sphinx
    ============================
    The main purpose of this extension is to use the nice C domain
    formatting of Sphinx, and to support DocBook assemblies.

    :copyright: 2016 Paolo Bonzini
    :license: MIT.
"""

import lxml.etree
import dbparser
import sphinx.parsers
import traceback

from os import path
from docutils import nodes
from sphinx import addnodes
from collections import defaultdict
from recommonmark.states import DummyStateMachine

__version__ = '0.0.1'
__contributors__ = ('Paolo Bonzini <pbonzini@redhat.com>')

class resource_placeholder(nodes.General, nodes.Element):
    pass

class DocbookAssemblyInfo(object):
    def __init__(self):
        self.children = defaultdict(list)
        self.assemblies = {}
        self.roots = set()

    # callbacks from SphinxDocbookConverter

    def add_child(self, parent, child, description):
        self.children[parent].append((description, child))

    def create_toctree(self, app, doctree, docname):
        if (docname in self.roots) or (not docname in self.children):
            return
        env = app.builder.env
        children = self.children[docname]
        tocnode = addnodes.toctree()
        tocnode['entries'] = children
        tocnode['includefiles'] = [x[1] for x in children]
        tocnode['glob'] = None
        env.note_toctree(docname, tocnode)
        wrapper = nodes.compound(classes=['toctree-wrapper'])
        wrapper += tocnode
        doctree += wrapper

    # Sphinx event callbacks

    def title_from_top_resource(self, app, env):
        for docname, top in self.assemblies.items():
            env.titles[docname] = env.titles[top]
            env.longtitles[docname] = env.longtitles[top]

    def replace_placeholders(self, app, doctree, docname):
        builder = app.builder
        env = builder.env
        for placeholder in doctree.traverse(resource_placeholder):
            target_doctree = env.get_doctree(placeholder.docname)
            env.resolve_references(target_doctree, placeholder.docname, builder)

            root = nodes.compound()
            for node in target_doctree.children:
                root += node.deepcopy()

            placeholder.replace_self(root.children)

    def purge(self, env, docname):
        if docname in self.assemblies:
            self.roots.remove(self.assemblies[docname])
            del self.assemblies[docname]
        for key in self.children.keys():
            self.children[key] = [x for x in self.children[key] if x[1] != docname]


class SphinxDocbookConverter(dbparser.DocbookConverter):
    _NS = '{https://pypi.python.org/pypi/db4sphinx}'
    _NSMAP = { _NS[1:-1]: 'sphinx' }

    _GENERIC_DOCROLES = {
        'command': addnodes.literal_strong,
        'dfn': nodes.emphasis,
        'kbd': nodes.literal,
        'mailheader': addnodes.literal_emphasis,
        'envar': addnodes.literal_strong,
        'manpage': addnodes.manpage,
        'program': addnodes.literal_strong,
    }

    def __init__(self, parser, document, ns):
        super(SphinxDocbookConverter, self).__init__(parser, document, ns)
        self.app = parser.app
        self.config = parser.config
        self.env = parser.env

        self.resource_base = None
        self.resources = {}
        self.descriptions = {}

        self.parent_docname = None
        self.current_docname = None
        self.current_resource = None
        self.current_depth = 0
        self.modules = None

    def convert_root(self, el):
        self.current_docname = self.env.docname
        super(SphinxDocbookConverter, self).convert_root(el)
        self.current_docname = None
        if hasattr(self.env, 'docbook_assembly_info'):
            self.env.docbook_assembly_info.create_toctree(
                    self.app, self.document, self.env.docname)

    def _run_directive(self, parent, name, arguments=None, options=None,
                       content=None):
        state_machine = DummyStateMachine()
        state_machine.reset(self.document, parent, self.current_level)
        if not content is None:
            content = content.split('\n')
        parent += state_machine.run_directive(name, arguments=arguments,
                                              options=options, content=content)

    def _run_role(self, parent, name, options=None, content=None):
        state_machine = DummyStateMachine()
        state_machine.reset(self.document, parent, self.current_level)
        parent += state_machine.run_role(name, options=options, content=content)

    # run rst roles and directives

    def e_sphinx_role(self, el, parent):
        # example
        #    <sphinx:role xmlns:sphinx="https://pypi.python.org/pypi/db4sphinx"
        #           sphinx:name="math">a+b</sphinx:role>

        attrs = dict(el.attrib)
        name = el.get(self._NS + 'name')
        del attrs[self._NS + 'name']
        self._run_role(parent, name, options=attrs, content=el.text)

    def e_sphinx_directive(self, el, parent):
        # FIXME: no support yet for more than one argument
        #    <sphinx:directive
        #           xmlns:sphinx="https://pypi.python.org/pypi/db4sphinx"
        #           sphinx:name="kernel-doc"
        #           sphinx:arg="../memory.h"
        #           export="address_space_*" />

        attrs = dict(el.attrib)
        name = el.get(self._NS + 'name')
        del attrs[self._NS + 'name']
        arg = el.get(self._NS + 'arg', None)
        if not arg is None:
            arguments = [arg]
            del attrs[self._NS + 'arg']
        else:
            arguments = None
        self._run_directive(parent, name, arguments=arguments,
                            options=attrs, content=el.text)

    def e_mathphrase(self, el, parent):
        if self._stack[-2] == 'inlineequation':
            self._run_role(parent, 'math', content=el.text)
        else:
            self._run_directive(parent, 'math', content=el.text)

    # assembly -> toctree conversion

    def e_assembly(self, el, parent):
        if not hasattr(self.env, 'docbook_assembly_info'):
            self.env.docbook_assembly_info = DocbookAssemblyInfo()
        xml_id = el.get(self._id_attrib) or None
        if not xml_id is None:
            parent['ids'].append(xml_id)
            self.document.set_id(parent)
        self.visit_children(el, parent)

    def e_resources(self, el, parent):
        self.resource_base = \
            el.get('{http://www.w3.org/XML/1998/namespace}base', '')
        self.visit_children(el, parent)

    def e_resource(self, el, parent):
        filename = path.join(self.resource_base, el.get('fileref'))
        filename, _ = self.env.relfn2path(filename)

        xml_id = el.get(self._id_attrib)
        description = el.find(self._ns + 'description')
        self.resources[xml_id] = filename
        if description is not None:
            self.descriptions[xml_id] = description.text

    def push_module(self, resourceref):
        filename = self.resources[resourceref]
        self.env.note_included(filename)
        docname = self.env.path2doc(filename)
        if not self.modules is None:
            self.modules.append(resourceref)

        save_parent_docname = self.parent_docname 
        save_current_resource = self.current_resource 
        save_modules = self.modules 
        self.parent_docname = self.current_docname
        self.current_docname = docname
        self.current_resource = resourceref
        self.current_depth = self.current_depth + 1
        self.modules = []
        return save_parent_docname, save_current_resource, save_modules

    def pop_module(self, state):
        self.current_depth = self.current_depth - 1
        self.current_docname = self.parent_docname
        self.parent_docname, self.current_resource, self.modules = state

    def include_resource(self, parent):
        resourceref = self.current_resource
        filename = self.resources[resourceref]

        docname = self.current_docname
        if self.current_depth == 1:
            self.env.docbook_assembly_info.assemblies[self.parent_docname] = docname
            self.env.docbook_assembly_info.roots.add(docname)

        placeholder = resource_placeholder()
        placeholder['ids'] = [resourceref]
        placeholder.docname = docname
        parent += placeholder

    def e_structure(self, el, parent):
        resourceref = el.get('resourceref')

        state = self.push_module(resourceref)
        self.include_resource(parent)

        # Add a hidden toctree to tell sphinx about the relationships between
        # modules
        tocnode = addnodes.toctree()
        tocnode['entries'] = []
        tocnode['includefiles'] = []
        tocnode['glob'] = None
        tocnode['hidden'] = True
        parent += tocnode

        # Add a bullet list which will link to the per-chapter links
        toclist = nodes.bullet_list()
        wrapper = nodes.compound(classes=['toctree-wrapper'])
        wrapper += toclist
        parent += wrapper

        self.visit_children(el, parent)
        for resourceref in self.modules:
            if resourceref in self.descriptions:
                # Add a reference to the bullet list
                description = self.descriptions[resourceref]
                node = nodes.reference()
                node['refid'] = resourceref
                node += nodes.Text(description)
                para = addnodes.compact_paragraph()
                para += node
                listitem = nodes.list_item()
                listitem += para
                toclist += listitem

                # Add an entry to the toctree
                filename = self.resources[resourceref]
                docname = self.env.path2doc(filename)
                tocnode['entries'].append((description, docname))
                tocnode['includefiles'].append(docname)

        self.pop_module(state)

    def e_module(self, el, parent):
        resourceref = el.get('resourceref')

        state = self.push_module(resourceref)
        if resourceref in self.descriptions:
            description = self.descriptions[resourceref]
            self.env.docbook_assembly_info.add_child(self.parent_docname,
                                                     self.current_docname,
                                                     description)

        if self.current_depth <= 2:
            self.include_resource(parent)
        self.visit_children(el, parent)
        self.pop_module(state)

    e_output = dbparser.DocbookConverter.nop


    # additional nodes

    def e_acronym(self, el, parent):
        self.concat(el, parent, addnodes.abbreviations)

    # API documentation

    def e_refentry(self, el, parent):
        self.concat(el, parent)

        # if the nice header was not built based on the prototype,
        # do it from the refname text
        if len(self._refname_node.children) == 0:
            if len(self._refname_parts) == 2:
                type_node = self.node(self._refname_node, addnodes.desc_type)
                type_node += self.text(self._refname_parts[0] + " ")
            name_node = self.node(self._refname_node, addnodes.desc_name)
            name_node += self.text(self._refname_parts[-1])

        self._refnamediv_node = None
        self._refname_node = None
        self._refname_parts = None

    def e_refnamediv(self, el, parent):
        node = self.create(el, parent, addnodes.desc)
        node['noindex'] = False
        node['domain'] = 'c'
        self._refnamediv_node = node
        self.concat_into(el, node, False)

    def e_refname(self, el, parent):
        node = self.create(el, parent, addnodes.desc_signature)
        node['first'] = False
        ids = []
        title, _ = self.no_markup_text(el, ids, False)
        self._refname_parts = title.split()
        self._refnamediv_node['ids'].append('c.' + self._refname_parts[-1])
        self._refname_node = node

    def e_refpurpose(self, el, parent):
        self.concat(el, parent, addnodes.desc_content)

    def e_refsynopsisdiv(self, el, parent):
        self.supports_only(el, (self._ns + "title",
                                 self._ns + "funcsynopsis",
                                 self._ns + "programlisting"))
        function = el.find(self._ns + "funcsynopsis")
        if function is None:
            self._refnamediv_node['objtype'] = 'type'
            self._refnamediv_node['desctype'] = 'type'
            listing = el.find(self._ns + "programlisting")
            if listing is not None:
                self.concat(listing, parent)
        else:
            self._refnamediv_node['objtype'] = 'function'
            self._refnamediv_node['desctype'] = 'function'
            self.concat_into(function, self._refname_node)

    def e_funcprototype(self, el, parent):
        self.supports_only(el, (self._ns + "funcdef",
                                self._ns + "paramdef"))

        funcdef = el.find(self._ns + "funcdef")
        self.supports_only(funcdef, (self._ns + "function"))
        desc_type = self.node(self._refname_node, addnodes.desc_type)
        desc_type += self.text(funcdef.text)

        function = funcdef.find(self._ns + "function")
        desc_name = self.node(self._refname_node, addnodes.desc_name)
        desc_name += self.text(function.text)

        desc_parameterlist = self.node(self._refname_node,
                                       addnodes.desc_parameterlist)
        paramdefs = el.findall(self._ns + "paramdef")
        for paramdef in paramdefs:
            self._conv(paramdef, desc_parameterlist)

    def e_paramdef(self, el, parent):
        self.supports_only(el, (self._ns + "parameter",
                                 self._ns + "funcparams"))
        node = self.concat(el, parent, addnodes.desc_parameter)
        node['noemph'] = True

class SphinxDocbookParser(dbparser.DocbookParser, sphinx.parsers.Parser):
    '''
    handle parsing of DocBook source code files
    for Sphinx
    '''

    converter = SphinxDocbookConverter

    def nested_parse(self, inputstring, state, parent):
        self.env = state.memo.document.settings.env
        self.app = self.env.app
        self.config = self.env.config
        dbparser.DocbookParser.nested_parse(self, inputstring, state, parent)

def purge_assembly_structure(app, env, docname):
    if hasattr(env, 'docbook_assembly_info'):
        env.docbook_assembly_info.purge(env, docname)

def process_assemblies_doctrees(app, doctree, docname):
    env = app.builder.env
    if hasattr(env, 'docbook_assembly_info'):
        env.docbook_assembly_info.replace_placeholders(app, doctree, docname)

def process_assemblies_env(app, env):
    if hasattr(env, 'docbook_assembly_info'):
        env.docbook_assembly_info.title_from_top_resource(app, env)

def setup(app):
    """Initialize Sphinx extension."""
    app.add_node(resource_placeholder)
    app.connect('doctree-resolved', process_assemblies_doctrees)
    app.connect('env-purge-doc', purge_assembly_structure)
    app.connect('env-updated', process_assemblies_env)
    app.add_source_parser('.xml', SphinxDocbookParser)  # needs Sphinx >= 1.4
    return {'version': __version__, 'parallel_read_safe': False}
