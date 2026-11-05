# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
# The package lives in src/ (src layout); CI also installs it with `pip install -e .`
sys.path.insert(0, os.path.abspath('../../src'))

project = 'pYsabelle'
copyright = '2026, davidebonav'
author = 'davidebonav'
release = '0.1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

templates_path = ['_templates']
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx_autodoc_typehints',
]

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'undoc-members': True,
    'show-inheritance': True,
    # Packages re-export their submodules' API via __all__: document each
    # object once, in the module that defines it.
    'ignore-module-all': True,
}
autodoc_typehints = 'description'
# Render Google-style 'Attributes:' as :ivar: fields, so dataclass fields
# documented by autodoc are not described twice.
napoleon_use_ivar = True


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
