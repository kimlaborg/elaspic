# -*- coding: utf-8 -*-
"""
Created on Sun Feb  3 15:07:51 2013

@author: niklas
"""
import os
import sys

###############################################################################
# Used to find the location of the files being executed
def we_are_frozen():
    # All of the modules are built-in to the interpreter, e.g., by py2exe
    return hasattr(sys, "frozen")

def path_to_pipeline_code():
    encoding = sys.getfilesystemencoding()
    if we_are_frozen():
        return os.path.dirname(unicode(sys.executable, encoding))
    return os.path.dirname(unicode(__file__, encoding))
    
    
###############################################################################    
# Keep track of and raise different kinds of errors
class TcoffeeError(Exception):
    def __init__(self, message, error, alignInFile):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)
        # Now for your custom code...
        self.error = 'tcoffee error for file: %s, with error message: %s' % (alignInFile, error)
        self.message = message

class TcoffeeBlastError(Exception):
    def __init__(self, message, error, alignInFile):
        Exception.__init__(self, message)
        self.error = 'tcoffee blast error for file: %s, with error message: %s' % (alignInFile, error)
        self.message = message
        
class TcoffeePDBidError(Exception):        
    def __init__(self, message, error, alignInFile):
        Exception.__init__(self, message)
        self.error = 'tcoffee pdbid error for file: %s, with error message: %s' % (alignInFile, error)
        


###############################################################################
# Common

class ProveanError(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = 'provean exited with an error:\n %s' % error







###############################################################################
# Finding templates

class pdbError(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error
        
class EmptyPDBSequenceError(Exception):
    def __init__(self, pdb_id, pdb_chain):
        Exception.__init__(self)
        self.error = 'Empty pdb sequence file for pdb: %s, chain: %s' % (pdb_id, pdb_chain)
        self.pdb_id = pdb_id
        self.pdb_chain = pdb_chain





###############################################################################
# Making models

class ModellError(Exception):
    pass

class FoldXError(Exception):
    def __init__(self, error):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self)
        self.error = error

class DataError(Exception):
    def __init__(self, inputFile):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self)
        self.inputFile = inputFile


class TemplateCoreError(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error

class TemplateInterfaceError(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error



###############################################################################
# Computing mutations

class PDBChainError(Exception):
    def __init__(self, pdb_code, chains):
        Exception.__init__(self)
        self.error = 'PDBChainError in pdb: %s and chain: %s' % (pdb_code, chains,)



class NoStructuralTemplates(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error

class NoSequenceFound(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error
        
        
        
class ProteinDefinitionError(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error
        
class NoTemplatesFound(Exception):
    def __init__(self, error):
        Exception.__init__(self)
        self.error = error


        
class NoPrecalculatedAlignmentFound(Exception):
    def __init__(self, save_path, alignment_filename):
        Exception.__init__(self)
        self.save_path = save_path
        self.alignment_filename = alignment_filename
        
class MutationOutsideDomain(Exception):
    def __init__(self):
        Exception.__init__(self)

class NotInteracting(Exception):
    def __init__(self):
        Exception.__init__(self)



class PopsError(Exception):
    def __init__(self, e, pdb, chains):
        Exception.__init__(self)
        self.error = e
        self.pdb = pdb
        self.chains = chains
        
class NoPDBFound(Exception):
    def __init__(self, pdb_filename):
        Exception.__init__(self)
        self.error = 'PDB with filename %s not found!' % pdb_filename
        

class NoDomainFound(Exception):
    def __init__(self, pdb_filename):
        Exception.__init__(self)
        self.error = 'PDB with filename %s not found!' % pdb_filename


###############################################################################

class MutationOutsideDomain(Exception):
    def __init__(self, uniprot_id, pfam_name, domain_def, mutation):
        Exception.__init__(self)
        self.uniprot_id = uniprot_id 
        self.pfam_name = pfam_name
        self.domain_def = domain_def
        self.mutation = mutation
        self.error = 'Mutation %s in uniprot %s falls outside pfam domain %s with domain defs %s' \
            % (mutation, uniprot_id, pfam_name, domain_def)


class MutationOutsideInterface(Exception):
    def __init__(self, uniprot_id_1, uniprot_id_2, pfam_name, mutation):
        Exception.__init__(self)
        self.uniprot_id_1 = uniprot_id_1
        self.uniprot_id_2 = uniprot_id_2
        self.pfam_name = pfam_name
        self.mutation = mutation
        self.error = 'Mutation %s in uniprot %s and pfam domain %s is not at the interface with %s' \
            % (mutation, uniprot_id_1, pfam_name, uniprot_id_2)
     
