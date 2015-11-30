# -*- coding: utf-8 -*-
"""
Created on Thu Nov  5 16:28:48 2015

@author: strokach
"""
import os
import os.path as op
import pep8
import pytest
import elaspic

list_of_files = [
    op.join(elaspic.BASE_DIR, f) for f in os.listdir(elaspic.BASE_DIR) if f.endswith('.py')
]


def test_pep8_conformance():
    """Test that we conform to PEP8."""
    pep8style = pep8.StyleGuide()
    result = pep8style.check_files(list_of_files)
    assert result.total_errors == 0


if __name__ == '__main__':
    pytest.main(['test_pep8.py', '-sv'])