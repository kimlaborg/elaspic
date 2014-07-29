# -*- coding: utf-8 -*-
"""
Created on Sun Feb  3 15:07:51 2013

@author: alexey
"""
import os
import pandas as pd
import urllib2
import subprocess
import json
from string import uppercase
import datetime
import logging
from contextlib import contextmanager
import cPickle as pickle
from collections import deque

from sqlalchemy import or_
from sqlalchemy import create_engine
from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy import Integer, Float, String, Boolean, Text, DateTime, Sequence
from sqlalchemy import ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, backref, aliased, scoped_session, joinedload
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.serializer import loads, dumps

from Bio import Seq
from Bio import SeqIO
from Bio import AlignIO

#import parse_pfamscan
import helper_functions as hf
import errors as error


###############################################################################
### Constants
# Not the best place to define this, bot collation changes depending on the
# database type...
#SQL_FLAVOUR = 'sqlite_file'
SQL_FLAVOUR = 'postgresql'

if SQL_FLAVOUR.split('_')[0] == 'sqlite': # sqlite_memory, sqlite_flatfile
    BINARY_COLLATION = 'RTRIM' # same as binary, except that trailing space characters are ignored.
#    STRING_COLLATION = 'NOCASE'
elif SQL_FLAVOUR.split('_')[0] == 'mysql':
    BINARY_COLLATION = 'utf8_bin'
#    STRING_COLLATION = 'utf8_unicode_ci'
elif SQL_FLAVOUR.split('_')[0] == 'postgresql':
    BINARY_COLLATION = 'en_US.utf8'
#    STRING_COLLATION = 'en_US.utf8'
else:
    raise Exception('Unknown database type!')

# Default sizes for creating varchar fields
SHORT = 15
MEDIUM = 255
LONG = 16384
SCHEMA_VERSION = 'elaspic_v5'

def get_index_list(table_name, index_columns):
    index_list = []
    for columns in index_columns:
        if type(columns) == tuple:
            columns, unique = columns
        elif type(columns) == list:
            unique = False
        index_list.append(
            Index('{}_{}'.format(table_name, '_'.join(columns)), *columns, unique=unique))
    return tuple(index_list)


###############################################################################
Base = declarative_base()

class Domain(Base):
    """ Table containing pdbfam domain definitions for all pdbs()
    """
    __tablename__ = 'domain'
    __table_args__ = (
        get_index_list(__tablename__, [
            ['pdb_id'],
            ['pdb_pdbfam_name'],
            ['pdb_id', 'pdb_chain'],
            (['pdb_id', 'pdb_chain', 'pdb_pdbfam_name', 'pdb_pdbfam_idx'], True)]) +
        ({'schema': SCHEMA_VERSION},)
    )

    cath_id = Column(String(SHORT, collation=BINARY_COLLATION),
                     index=True, nullable=False, primary_key=True)
    pdb_id = Column(String(SHORT), nullable=False)
    pdb_type = Column(String(MEDIUM), nullable=True)
    pdb_resolution = Column(Float, nullable=True)
    pdb_chain = Column(String(SHORT), nullable=False)
    pdb_domain_def = Column(String(MEDIUM), nullable=False)
    pdb_pdbfam_name = Column(String(LONG), nullable=False)
    pdb_pdbfam_idx = Column(Integer)
    domain_errors = Column(Text)


class DomainContact(Base):
    """ Table containing interactions between all pdbfam domains in the pdb
    """
    __tablename__ = 'domain_contact'
    __table_args__ = (
        get_index_list(__tablename__, [
            (['cath_id_1', 'cath_id_2'], True)]) +
        ({'schema': SCHEMA_VERSION},)
    )

    domain_contact_id = Column(Integer, index=True, nullable=False, primary_key=True)
    cath_id_1 = Column(None, ForeignKey(Domain.cath_id, onupdate='cascade', ondelete='cascade'), index=True, nullable=False)
    cath_id_2 = Column(String(SHORT, collation=BINARY_COLLATION), index=True, nullable=False)
    min_interchain_distance = Column(Float)
    contact_volume = Column(Float)
    contact_surface_area = Column(Float)
    atom_count_1 = Column(Integer)
    atom_count_2 = Column(Integer)
    contact_residues_1 = Column(Text)
    contact_residues_2 = Column(Text)
    crystal_packing = Column(Float)
    domain_contact_errors = Column(Text)

    # Relationships
    domain_1 = relationship(Domain, primaryjoin=cath_id_1==Domain.cath_id, cascade='expunge', lazy='joined')
    #domain_2 = relationship(Domain, primaryjoin=cath_id_2==Domain.cath_id, cascade='expunge', lazy='joined')


class UniprotSequence(Base):
    """ Table containing the entire Swissprot + Trembl database as well as any
    additional sequences that were added to the database.
    """
    __tablename__ = 'uniprot_sequence'
    __table_args__ = ({'schema': 'uniprot_kb'},)

    db = Column(String(SHORT), nullable=False)
    uniprot_id = Column(String(SHORT), index=True, nullable=False, primary_key=True)
    uniprot_name = Column(String(SHORT), nullable=False)
    protein_name = Column(String(MEDIUM))
    organism_name = Column(String(MEDIUM))
    gene_name = Column(String(MEDIUM))
    protein_existence = Column(Integer)
    sequence_version = Column(Integer)
    uniprot_sequence = Column(Text, nullable=False)


class Provean(Base):
    __tablename__ = 'provean'
    __table_args__ = ({'schema': SCHEMA_VERSION})

    uniprot_id = Column(None, ForeignKey(UniprotSequence.uniprot_id, onupdate='cascade', ondelete='cascade'),
                        index=True, nullable=False, primary_key=True)
    provean_supset_filename = Column(String(MEDIUM))
    provean_supset_length = Column(Integer)
    provean_errors = Column(Text)
    provean_date_modified = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    uniprot_sequence = relationship(
        UniprotSequence, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('provean', uselist=False, cascade='expunge', lazy='joined'))


class UniprotDomain(Base):
    __tablename__ = 'uniprot_domain'
    __table_args__ = (
        UniqueConstraint('uniprot_id', 'pdbfam_name', 'alignment_def', name='unique_uniprot_domain'),
        {'sqlite_autoincrement': True, 'schema': SCHEMA_VERSION},
    )

    uniprot_domain_id = Column(Integer, index=True, nullable=False, primary_key=True, autoincrement=True)
    uniprot_id = Column(None, ForeignKey(UniprotSequence.uniprot_id, onupdate='cascade', ondelete='cascade'),
                        index=True, nullable=False)
#    uniprot_name = Column(Text)
    pdbfam_name = Column(String(LONG), index=True, nullable=False)
    pdbfam_idx = Column(Integer, nullable=False)
    pfam_clan = Column(String(LONG))
    alignment_def = Column(String(MEDIUM))
    pfam_names = Column(String(LONG))
    alignment_subdefs = Column(String(LONG))
    path_to_data = Column(Text)
    # Relationships
    uniprot_sequence = relationship(
        UniprotSequence, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('uniprot_domain', cascade='expunge')) # many to one



class UniprotDomainPair(Base):
    __tablename__ = 'uniprot_domain_pair'
    __table_args__ = (
        get_index_list(__tablename__, [
            (['uniprot_domain_id_1', 'uniprot_domain_id_2'], True) ]) +
        ({'sqlite_autoincrement': True, 'schema': SCHEMA_VERSION},) )

    uniprot_domain_pair_id = Column(Integer, index=True, nullable=False, primary_key=True, autoincrement=True)
    uniprot_domain_id_1 = Column(None, ForeignKey(UniprotDomain.uniprot_domain_id, onupdate='cascade', ondelete='cascade'),
                                 index=True, nullable=False)
#    uniprot_id_1 = Column(String(SHORT))
    uniprot_domain_id_2 = Column(None, ForeignKey(UniprotDomain.uniprot_domain_id, onupdate='cascade', ondelete='cascade'),
                                 index=True, nullable=False)
#    uniprot_id_2 = Column(String(SHORT))
    rigids = Column(Text) # Interaction references from iRefIndex
    domain_contact_ids = Column(Text) # interaction references from PDBfam
    path_to_data = Column(Text)


    # Relationships
    uniprot_domain_1 = relationship(
        UniprotDomain,
        primaryjoin=uniprot_domain_id_1==UniprotDomain.uniprot_domain_id,
        cascade='expunge', lazy='joined') # many to one
    uniprot_domain_2 = relationship(
        UniprotDomain,
        primaryjoin=uniprot_domain_id_2==UniprotDomain.uniprot_domain_id,
        cascade='expunge', lazy='joined') # many to one




class UniprotDomainTemplate(Base):
    __tablename__ = 'uniprot_domain_template'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_domain_id = Column(None, ForeignKey(UniprotDomain.uniprot_domain_id, onupdate='cascade', ondelete='cascade'),
                               index=True, nullable=False, primary_key=True)
    template_errors = Column(Text)
    cath_id = Column(None, ForeignKey(Domain.cath_id, onupdate='cascade', ondelete='cascade'), index=True, nullable=False)
    domain_start = Column(Integer)
    domain_end = Column(Integer)
    domain_def = Column(String(MEDIUM))
    alignment_identity = Column(Float)
    alignment_coverage = Column(Float)
    alignment_score = Column(Float)
    t_date_modified = Column(DateTime, default=datetime.datetime.utcnow,
                             onupdate=datetime.datetime.utcnow, nullable=False)
    # Relationships
    uniprot_domain = relationship(
        UniprotDomain, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('template', uselist=False, cascade='expunge', lazy='joined')) # one to one
    domain = relationship(
        Domain, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('uniprot_domain', cascade='expunge')) # many to one



class UniprotDomainModel(Base):
    __tablename__ = 'uniprot_domain_model'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_domain_id = Column(
        None, ForeignKey(UniprotDomainTemplate.uniprot_domain_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False, primary_key=True)
    model_errors = Column(Text)
    alignment_filename = Column(String(MEDIUM))
    model_filename = Column(String(MEDIUM))
    chain = Column(String(SHORT))
    norm_dope = Column(Float)
    sasa_score = Column(Text)
    m_date_modified = Column(DateTime, default=datetime.datetime.utcnow,
                             onupdate=datetime.datetime.utcnow, nullable=False)
    # Relationships
    template = relationship(
        UniprotDomainTemplate, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('model', uselist=False, cascade='expunge', lazy='joined')) # one to one



class UniprotDomainMutation(Base):
    __tablename__ = 'uniprot_domain_mutation'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_id = Column(None, ForeignKey(UniprotSequence.uniprot_id, onupdate='cascade', ondelete='cascade'),
                        index=True, nullable=False, primary_key=True)
    uniprot_domain_id = Column(None, ForeignKey(UniprotDomainModel.uniprot_domain_id, onupdate='cascade', ondelete='cascade'),
                               index=True, nullable=False, primary_key=True)
    mutation = Column(String(SHORT),
                      index=True, nullable=False, primary_key=True)
    mutation_errors = Column(Text)
    model_filename_wt = Column(String(MEDIUM))
    model_filename_mut = Column(String(MEDIUM))
    chain_modeller = Column(String(SHORT))
    mutation_modeller = Column(String(SHORT))
    stability_energy_wt = Column(Text)
    stability_energy_mut = Column(Text)
    physchem_wt = Column(Text)
    physchem_wt_ownchain = Column(Text)
    physchem_mut = Column(Text)
    physchem_mut_ownchain = Column(Text)
    matrix_score = Column(Float)
    secondary_structure_wt = Column(Text)
    solvent_accessibility_wt = Column(Float)
    secondary_structure_mut = Column(Text)
    solvent_accessibility_mut = Column(Float)
    provean_score = Column(Float)
    ddg = Column(Float)
    mut_date_modified = Column(DateTime, default=datetime.datetime.utcnow,
                               onupdate=datetime.datetime.utcnow, nullable=False)
    # Relationships
    model = relationship(
        UniprotDomainModel, cascade='expunge', uselist=False, lazy='joined',
        backref=backref('mutations', cascade='expunge')) # many to one



class UniprotDomainPairTemplate(Base):
    __tablename__ = 'uniprot_domain_pair_template'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_domain_pair_id = Column(
        None, ForeignKey(UniprotDomainPair.uniprot_domain_pair_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False, primary_key=True)
    domain_contact_id = Column(
        None, ForeignKey(DomainContact.domain_contact_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False)
    cath_id_1 = Column(
        None, ForeignKey(Domain.cath_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False)
    cath_id_2 = Column(
        None, ForeignKey(Domain.cath_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False)

    identical_1 = Column(Float)
    conserved_1 = Column(Float)
    coverage_1 = Column(Float)
    score_1 = Column(Float)

    identical_if_1 = Column(Float)
    conserved_if_1 = Column(Float)
    coverage_if_1 = Column(Float)
    score_if_1 = Column(Float)

    identical_2 = Column(Float)
    conserved_2 = Column(Float)
    coverage_2 = Column(Float)
    score_2 = Column(Float)

    identical_if_2 = Column(Float)
    conserved_if_2 = Column(Float)
    coverage_if_2 = Column(Float)
    score_if_2 = Column(Float)

    score_total = Column(Float)
    score_if_total = Column(Float)
    score_overall = Column(Float)

    t_date_modified = Column(
        DateTime, default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow, nullable=False)
    template_errors = Column(Text)

    # Relationships
    domain_pair = relationship(
        UniprotDomainPair, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('template', uselist=False, cascade='expunge', lazy='joined')) # one to one
    domain_contact = relationship(
        DomainContact, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('uniprot', cascade='expunge')) # one to one
    domain_1 = relationship(
        Domain, uselist=False, cascade='expunge', lazy='joined',
        primaryjoin=(cath_id_1==Domain.cath_id)) # many to one
    domain_2 = relationship(
        Domain, uselist=False, cascade='expunge', lazy='joined',
        primaryjoin=(cath_id_2==Domain.cath_id)) # many to one



class UniprotDomainPairModel(Base):
    __tablename__ = 'uniprot_domain_pair_model'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_domain_pair_id = Column(
        None, ForeignKey(UniprotDomainPairTemplate.uniprot_domain_pair_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False, primary_key=True)
    model_errors = Column(Text)
    alignment_filename_1 = Column(String(MEDIUM))
    alignment_filename_2 = Column(String(MEDIUM))
    model_filename = Column(String(MEDIUM))
    chain_1 = Column(String(SHORT))
    chain_2 = Column(String(SHORT))
    norm_dope = Column(Float)
    interface_area_hydrophobic = Column(Float)
    interface_area_hydrophilic = Column(Float)
    interface_area_total = Column(Float)
    interface_dg = Column(Float)
    interacting_aa_1 = Column(Text)
    interacting_aa_2 = Column(Text)
    m_date_modified = Column(DateTime, default=datetime.datetime.utcnow,
                             onupdate=datetime.datetime.utcnow, nullable=False)
    # Relationships
    template = relationship(
        UniprotDomainPairTemplate, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('model', uselist=False, cascade='expunge', lazy='joined')) # one to one



class UniprotDomainPairMutation(Base):
    __tablename__ = 'uniprot_domain_pair_mutation'
    __table_args__ = ({'schema': SCHEMA_VERSION},)

    uniprot_id = Column(None, ForeignKey(
        UniprotSequence.uniprot_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False, primary_key=True)
    uniprot_domain_pair_id = Column(None, ForeignKey(
        UniprotDomainPairModel.uniprot_domain_pair_id, onupdate='cascade', ondelete='cascade'),
        index=True, nullable=False, primary_key=True)
    mutation = Column(String(SHORT),
        index=True, nullable=False, primary_key=True)
    mutation_errors = Column(Text)
    model_filename_wt = Column(String(MEDIUM))
    model_filename_mut = Column(String(MEDIUM))
    chain_modeller = Column(String(SHORT))
    mutation_modeller = Column(String(SHORT))
    analyse_complex_energy_wt = Column(Text)
    stability_energy_wt = Column(Text)
    analyse_complex_energy_mut = Column(Text)
    stability_energy_mut = Column(Text)
    physchem_wt = Column(Text)
    physchem_wt_ownchain = Column(Text)
    physchem_mut = Column(Text)
    physchem_mut_ownchain = Column(Text)
    matrix_score = Column(Float)
    secondary_structure_wt = Column(Text)
    solvent_accessibility_wt = Column(Float)
    secondary_structure_mut = Column(Text)
    solvent_accessibility_mut = Column(Float)
    contact_distance_wt = Column(Float)
    contact_distance_mut = Column(Float)
    provean_score = Column(Float)
    ddg = Column(Float)
    mut_date_modified = Column(DateTime, default=datetime.datetime.utcnow,
                               onupdate=datetime.datetime.utcnow, nullable=False)
    # Relationships
    model = relationship(
        UniprotDomainPairModel, uselist=False, cascade='expunge', lazy='joined',
        backref=backref('mutations', cascade='expunge')) # many to one


irefindex_materialized_view_command = ("""
CREATE MATERIALIZED VIEW {0}.irefindex_interactions AS
SELECT
mi.rigid,
ma1.alias uniprot_name_1,
up1.uniprot_id uniprot_id_1,
ma2.alias uniprot_name_2,
up2.uniprot_id uniprot_id_2
FROM mitab_irefindex.mitab_interactions mi
JOIN mitab_irefindex.mitab_aliases ma1 ON (ma1.uid = mi.uida)
JOIN mitab_irefindex.mitab_aliases ma2 ON (ma2.uid = mi.uidb)
JOIN uniprot_kb.uniprot_sequence up1 ON (up1.uniprot_name = ma1.alias)
JOIN uniprot_kb.uniprot_sequence up2 ON (up2.uniprot_name = ma2.alias)
WHERE ma1.dbname = 'uniprotkb'
AND ma2.dbname = 'uniprotkb'
AND up1.uniprot_id NOT LIKE '%%-%%'
AND up2.uniprot_id NOT LIKE '%%-%%';

CREATE INDEX irefindex_interactions_uniprot_name_1_idx ON {0}.irefindex_interactions (uniprot_name_1);
CREATE INDEX irefindex_interactions_uniprot_name_2_idx ON {0}.irefindex_interactions (uniprot_name_2);
CREATE INDEX irefindex_interactions_uniprot_name_1_uniprot_name_2_idx ON {0}.irefindex_interactions (uniprot_name_1, uniprot_name_2);
CREATE INDEX irefindex_interactions_uniprot_id_1_idx ON {0}.irefindex_interactions (uniprot_id_1);
CREATE INDEX irefindex_interactions_uniprot_id_2_idx ON {0}.irefindex_interactions (uniprot_id_2);
CREATE INDEX irefindex_interactions_uniprot_id_1_uniprot_id_2_idx ON {0}.irefindex_interactions (uniprot_id_1, uniprot_id_2);
CREATE INDEX irefindex_interactions_rigid_idx ON {0}.irefindex_interactions (rigid);
""".format(SCHEMA_VERSION))


pdbfam_name_to_pfam_clan_materialized_view_command = ("""
CREATE MATERIALIZED VIEW {0}.pdbfam_name_to_pfam_clan AS
SELECT DISTINCT pdbfam_name, pfam_clan
FROM elaspic_v5.uniprot_domain;

CREATE INDEX pdbfam_name_to_pfam_clan_pdbfam_name_idx ON {0}.pdbfam_name_to_pfam_clan (pdbfam_name);
CREATE INDEX pdbfam_name_to_pfam_clan_pfam_clan_idx ON {0}.pdbfam_name_to_pfam_clan (pfam_clan);
CREATE UNIQUE INDEX pdbfam_name_to_pfam_clan_pdbfam_name_pfam_clan_idx ON {0}.pdbfam_name_to_pfam_clan (pdbfam_name, pfam_clan);
""")



###############################################################################
# Get the session that will be used for all future queries
# Expire on commit so that you keep all the table objects even after the
# session closes.
Session = sessionmaker(expire_on_commit=False)
#Session = scoped_session(sessionmaker(expire_on_commit=False))

class MyDatabase(object):
    """
    """
    def __init__(
            self, sql_flavour=SQL_FLAVOUR, is_immutable=False,
            temp_path='/tmp/', path_to_archive='/home/kimlab1/database_data/elaspic/',
            path_to_sqlite_db='', create_database=False, clear_schema=False, logger=None):

        # Choose which database to use
        if SQL_FLAVOUR == 'sqlite':
            autocommit=True
            autoflush=True
            engine = create_engine('sqlite://')
        elif SQL_FLAVOUR == 'sqlite_file':
            autocommit=True
            autoflush=True
            engine = create_engine('sqlite:///' + path_to_sqlite_db, isolation_level='READ UNCOMMITTED')
        elif SQL_FLAVOUR == 'postgresql':
            autocommit=False
            autoflush=False
            engine = create_engine('postgresql://elaspic:elaspic@192.168.6.19:5432/kimlab') # , echo=True

        if logger is None:
            logger = logging.getLogger(__name__)
            logger.handlers = []
            logger.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)
        self.logger = logger

        if create_database:
            self._create_database(engine, clear_schema)

        Session.configure(bind=engine, autocommit=autocommit, autoflush=autoflush)
        self.Session = Session
        self.autocommit = autocommit
        self.is_immutable = is_immutable
        self.temp_path = temp_path
        self.path_to_archive = path_to_archive


    def _create_database(self, engine, clear_schema):
        """ Creating a new database in the schema specified by the
        'SCHEMA_VERSION' global variable.
        If 'clear_schema' == True, remove all the tables in the schema first.
        """
        metadata_tables = Base.metadata.tables.copy()
        del metadata_tables['uniprot_kb.uniprot_sequence']
        if clear_schema:
            Base.metadata.drop_all(engine, metadata_tables.values())
        Base.metadata.create_all(engine, metadata_tables.values())
#        engine.execute(irefindex_materialized_view_command)


    @contextmanager
    def session_scope(self):
        """ Provide a transactional scope around a series of operations.
        So you can use: `with self.session_scope() as session:`
        """
        session = self.Session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()


    ###########################################################################
    # Get objects from the database

    def get_rows_by_ids(self, row_object, row_object_identifiers, row_object_identifier_values):
        """ Get the rows from the table *row_object* identified by keys
        *row_object_identifiers* with values *row_object_identifier_values*
        """
        with self.session_scope() as session:
            if len(row_object_identifiers) != len(row_object_identifier_values):
                raise Exception(
                    'The number of identifiers and the number of identifier '
                    'values must be the same.')
            if len(row_object_identifiers) > 3:
                raise Exception(
                    'Too many identifiers provied. The function is hard-coded '
                    'to handle at most three identifiers.')
            if len(row_object_identifiers) == 1:
                row_instances = (
                    session.query(row_object)
                    .filter(row_object_identifiers[0] == row_object_identifier_values[0])
                    .all())
            if len(row_object_identifiers) == 2:
                row_instances = (
                    session.query(row_object)
                    .filter(row_object_identifiers[0] == row_object_identifier_values[0])
                    .filter(row_object_identifiers[1] == row_object_identifier_values[1])
                    .all())
            if len(row_object_identifiers) == 3:
                row_instances = (
                    session.query(row_object)
                    .filter(row_object_identifiers[0] == row_object_identifier_values[0])
                    .filter(row_object_identifiers[1] == row_object_identifier_values[1])
                    .filter(row_object_identifiers[2] == row_object_identifier_values[2])
                    .all())
            return row_instances


    def get_domain(self, pfam_names, subdomains=False):
        """ Contains pdbfam-based definitions of all pfam domains in the pdb
        """
        with self.session_scope() as session:
            domain_set = set()
            for pfam_name in pfam_names:
                if not subdomains:
                    domain = (
                        session.query(Domain)
                        .filter(Domain.pfam_name==pfam_name)
                        .distinct().all() )
                else:
                    domain = (
                        session.query(Domain).filter(
                            (Domain.pfam_name.like(pfam_name)) |
                            (Domain.pfam_name.like(pfam_name+'+%')) |
                            (Domain.pfam_name.like(pfam_name+'\_%')) | # need an escape character because _ matches any single character
                            (Domain.pfam_name.like('%+'+pfam_name)) |
                            (Domain.pfam_name.like('%+'+pfam_name+'+%')) |
                            (Domain.pfam_name.like('%+'+pfam_name+'\_%')) ) # need an escape character because _ matches any single character
                        .distinct().all() )
                domain_set.update(domain)
        if not domain_set:
            self.logger.debug('No domain definitions found for pfam: %s' % str(pfam_names))
        return list(domain_set)


    def get_domain_contact(self, pfam_names_1, pfam_names_2, subdomains=False):
        """ Keeps the domain-domain interaction information from pdbfam
        Note that the produced dataframe may not have the same order as the keys
        """
        with self.session_scope() as session:
            domain_contact_1 = self._get_domain_contact(pfam_names_1, pfam_names_2, session, subdomains)
            domain_contact_2 = self._get_domain_contact(pfam_names_2, pfam_names_1, session, subdomains)

        if not len(domain_contact_1) and not len(domain_contact_2):
            self.logger.debug('No domain contact template found for domains %s, %s' % (str(pfam_names_1), str(pfam_names_2),))

        return [domain_contact_1, domain_contact_2]


    def _get_domain_contact(self, pfam_names_1, pfam_names_2, session, subdomains):
        """
        """
        domain_1 = aliased(Domain)
        domain_2 = aliased(Domain)
        domain_contact_set = set()
        for pfam_name_1 in pfam_names_1:
            for pfam_name_2 in pfam_names_2:
                if not subdomains:
                    domain_contact = (
                        session.query(DomainContact)
                        # .join(domain_1, DomainContact.cath_id_1==domain_1.cath_id)
                        .filter(domain_1.pfam_name==pfam_name_1)
                        # .join(domain_2, DomainContact.cath_id_2==domain_2.cath_id)
                        .filter(domain_2.pfam_name==pfam_name_2)
                        .distinct().all() )
                else:
                    domain_contact = (
                        session.query(DomainContact)
                        # .join(domain_1, DomainContact.cath_id_1==domain_1.cath_id)
                        .filter(
                            (domain_1.pfam_name.like(pfam_name_1)) |
                            (domain_1.pfam_name.like(pfam_name_1+'+%')) |
                            (domain_1.pfam_name.like(pfam_name_1+'\_%')) | # need an escape character because _ matches any single character
                            (domain_1.pfam_name.like('%+'+pfam_name_1)) |
                            (domain_1.pfam_name.like('%+'+pfam_name_1+'+%')) |
                            (domain_1.pfam_name.like('%+'+pfam_name_1+'\_%')) ) # need an escape character because _ matches any single character
                        # .join(domain_2, DomainContact.cath_id_2==domain_2.cath_id)
                        .filter(
                            (domain_2.pfam_name.like(pfam_name_2)) |
                            (domain_2.pfam_name.like(pfam_name_2+'+%')) |
                            (domain_2.pfam_name.like(pfam_name_2+'\_%')) | # need an escape character because _ matches any single character
                            (domain_2.pfam_name.like('%+'+pfam_name_2)) |
                            (domain_2.pfam_name.like('%+'+pfam_name_2+'+%')) |
                            (domain_2.pfam_name.like('%+'+pfam_name_2+'\_%')) ) # need an escape character because _ matches any single character
                        .distinct().all() )
                domain_contact_set.update(domain_contact)
        return list(domain_contact_set)


    def get_uniprot_domain(self, uniprot_id, copy_data=False):
        """
        """
        with self.session_scope() as session:
            uniprot_domains = (
                session
                    .query(UniprotDomain)
                    .filter(UniprotDomain.uniprot_id == uniprot_id)
                    # .options(joinedload('model'))
                    .all() )

        d_idx = 0
        while d_idx < len(uniprot_domains):
            d = uniprot_domains[d_idx]
            if not d.template:
                self.logger.debug(
                    'Skipping uniprot domain with id {} because it does not '
                    'have a structural template...'.format(d.uniprot_domain_id))
                del uniprot_domains[d_idx]
                continue
            if copy_data and d.template.model:
                self._copy_uniprot_domain_data(d, d.path_to_data)
            d_idx += 1

        return uniprot_domains


    def get_uniprot_domain_pair(self, uniprot_id, copy_data=False):
        """
        """
        with self.session_scope() as session:
            uniprot_domain_pairs = (
                session.query(UniprotDomainPair)
                .filter(or_(
                    "uniprot_domain_1.uniprot_id='{}'".format(uniprot_id),
                    "uniprot_domain_2.uniprot_id='{}'".format(uniprot_id)))
                # .options(joinedload('model'))
                .all() )

        d_idx = 0
        while d_idx < len(uniprot_domain_pairs):
            d = uniprot_domain_pairs[d_idx]
            if not d.template:
                self.logger.debug(
                    'Skipping uniprot domain pair with id {} because it does not '
                    'have a structural template...'.format(d.uniprot_domain_pair_id))
                del uniprot_domain_pairs[d_idx]
                continue
            if copy_data and d.template.model:
                self._copy_uniprot_domain_pair_data(d, d.path_to_data, uniprot_id)
            d_idx += 1

        return uniprot_domain_pairs


    def _copy_uniprot_domain_data(self, d, path_to_data):
        if (path_to_data
                and d.template
                and d.template.model
                and d.template.model.alignment_filename
                and d.template.model.model_filename):
            tmp_save_path = self.temp_path + path_to_data
            archive_save_path = self.path_to_archive + path_to_data
            path_to_alignment = tmp_save_path + '/'.join(d.template.model.alignment_filename.split('/')[:-1]) + '/'
            subprocess.check_call('mkdir -p {}'.format(path_to_alignment), shell=True)
            subprocess.check_call('cp -f {} {}'.format(
                archive_save_path + d.template.model.alignment_filename,
                tmp_save_path + d.template.model.alignment_filename), shell=True)
            subprocess.check_call('cp -f {} {}'.format(
                archive_save_path + d.template.model.model_filename,
                tmp_save_path + d.template.model.model_filename), shell=True)
            # Copy Provean supporting set
            self._copy_provean(d)



    def _copy_uniprot_domain_pair_data(self, d, path_to_data, uniprot_id):
        if (path_to_data
                and d.template.model.alignment_filename_1
                and d.template.model.alignment_filename_2
                and d.template.model.model_filename):
            tmp_save_path = self.temp_path + path_to_data
            archive_save_path = self.path_to_archive + path_to_data
            path_to_alignment_1 = tmp_save_path + '/'.join(d.template.model.alignment_filename_1.split('/')[:-1]) + '/'
            path_to_alignment_2 = tmp_save_path + '/'.join(d.template.model.alignment_filename_2.split('/')[:-1]) + '/'
            subprocess.check_call('mkdir -p {}'.format(path_to_alignment_1), shell=True)
            subprocess.check_call('mkdir -p {}'.format(path_to_alignment_2), shell=True)
            subprocess.check_call('cp -f {} {}'.format(
                archive_save_path + d.template.model.alignment_filename_1,
                tmp_save_path + d.template.model.alignment_filename_1), shell=True)
            subprocess.check_call('cp -f {} {}'.format(
                archive_save_path + d.template.model.alignment_filename_2,
                tmp_save_path + d.template.model.alignment_filename_2), shell=True)
            subprocess.check_call('cp -f {} {}'.format(
                archive_save_path + d.template.model.model_filename,
                tmp_save_path + d.template.model.model_filename), shell=True)
            # Copy Provean supporting set
            if d.uniprot_domain_1.uniprot_id == uniprot_id:
                self._copy_provean(d.uniprot_domain_1)
            elif d.uniprot_domain_2.uniprot_id == uniprot_id:
                self._copy_provean(d.uniprot_domain_2)


    def _copy_provean(self, ud):
        if (ud.uniprot_sequence
                and ud.uniprot_sequence.provean
                and ud.uniprot_sequence.provean.provean_supset_filename):
            try:
                subprocess.check_call('cp -f {} {}'.format(
                    self.path_to_archive + hf.get_uniprot_base_path(ud) +
                        ud.uniprot_sequence.provean.provean_supset_filename,
                    self.temp_path + hf.get_uniprot_base_path(ud) +
                        ud.uniprot_sequence.provean.provean_supset_filename), shell=True)
                subprocess.check_call('cp -f {} {}'.format(
                    self.path_to_archive + hf.get_uniprot_base_path(ud) +
                        ud.uniprot_sequence.provean.provean_supset_filename + '.fasta',
                    self.temp_path + hf.get_uniprot_base_path(ud) +
                        ud.uniprot_sequence.provean.provean_supset_filename + '.fasta'), shell=True)
            except Exception as e:
                self.logger.error('Could not copy provean supporting set files!!!')
                self.logger.error(str(e))
                self.logger.error('Removing provean info')
                ud.uniprot_sequence.provean.provean_supset_filename = ''


    def get_uniprot_mutation(self, d, mutation, uniprot_id=None, copy_data=False):
        """
        """
        if isinstance(d, UniprotDomain):
            with self.session_scope() as session:
                uniprot_mutation = (
                    session.query(UniprotDomainMutation)
                        .filter(
                            (UniprotDomainMutation.uniprot_domain_id == d.uniprot_domain_id) &
                            (UniprotDomainMutation.mutation == mutation))
                        .scalar() )
        elif isinstance(d, UniprotDomainPair) and isinstance(uniprot_id, basestring):
            with self.session_scope() as session:
                uniprot_mutation = (
                    session.query(UniprotDomainPairMutation)
                        .filter(
                            (UniprotDomainPairMutation.uniprot_id == uniprot_id) &
                            (UniprotDomainPairMutation.uniprot_domain_pair_id == d.uniprot_domain_pair_id) &
                            (UniprotDomainPairMutation.mutation == mutation))
                        .scalar() )
        else:
            raise Exception('Not enough arguments, or the argument types are incorrect!')

        if uniprot_mutation:
            self._copy_mutation_data(uniprot_mutation, d.path_to_data)
        return uniprot_mutation


    def _copy_mutation_data(self, mutation, path_to_data):
        tmp_save_path = self.temp_path + path_to_data
        archive_save_path = self.path_to_archive + path_to_data
        path_to_mutation = tmp_save_path + '/'.join(mutation.model_filename_wt.split('/')[:-1]) + '/'
        subprocess.check_call('mkdir -p {}'.format(path_to_mutation), shell=True)
        subprocess.check_call('cp -f {} {}'.format(
            archive_save_path + mutation.model_filename_wt,
            tmp_save_path + mutation.model_filename_wt), shell=True)
        subprocess.check_call('cp -f {} {}'.format(
            archive_save_path + mutation.model_filename_mut,
            tmp_save_path + mutation.model_filename_mut), shell=True)


    ###########################################################################
    # Add objects from the database
    def merge_row(self, row_instance):
        """ Add a list of rows *row_instances* to the database
        """
        if not self.is_immutable:
            with self.session_scope() as session:
                if not isinstance(row_instance, list):
                    session.merge(row_instance)
                else:
                    deque( (session.merge(row) for row in row_instance), maxlen=0 )


    def merge_provean(self, provean, uniprot_base_path):
        if (provean.provean_supset_filename and
                os.path.isfile(self.temp_path + uniprot_base_path +
                    provean.provean_supset_filename) and
                os.path.isfile(self.temp_path + uniprot_base_path +
                    provean.provean_supset_filename + '.fasta') ):
            self.logger.debug('Moving provean supset to the output folder: {}'.format(self.path_to_archive + uniprot_base_path))
            subprocess.check_call('mkdir -p ' + self.path_to_archive + uniprot_base_path, shell=True)
            subprocess.check_call(
                'cp -f ' + self.temp_path + uniprot_base_path + provean.provean_supset_filename +
                ' ' + self.path_to_archive + uniprot_base_path + provean.provean_supset_filename, shell=True)
            subprocess.check_call(
                'cp -f ' + self.temp_path + uniprot_base_path + provean.provean_supset_filename + '.fasta' +
                ' ' + self.path_to_archive + uniprot_base_path + provean.provean_supset_filename + '.fasta', shell=True)
        self.merge_row(provean)


    def merge_model(self, d, path_to_data=False):
        """
        """
        # Save a copy of the alignment to the export folder
        if path_to_data:
            tmp_save_path = self.temp_path + path_to_data
            archive_save_path = self.path_to_archive + path_to_data
            # Save the row corresponding to the model as a serialized sqlalchemy object
            subprocess.check_call('mkdir -p ' + archive_save_path, shell=True)
            pickle.dump(dumps(d.template), open(archive_save_path + 'template.pickle', 'wb'), pickle.HIGHEST_PROTOCOL)
            pickle.dump(dumps(d.template.model), open(archive_save_path + 'model.pickle', 'wb'), pickle.HIGHEST_PROTOCOL)
            # Save the modelled structure
            if d.template.model.model_filename is not None:
                # Save alignments
                if isinstance(d.template.model, UniprotDomainModel):
                    subprocess.check_call('cp -f ' + tmp_save_path + d.template.model.alignment_filename +
                        ' ' + archive_save_path + d.template.model.alignment_filename, shell=True)
                elif isinstance(d.template.model, UniprotDomainPairModel):
                    subprocess.check_call('cp -f ' + tmp_save_path + d.template.model.alignment_filename_1 +
                        ' ' + archive_save_path + d.template.model.alignment_filename_1, shell=True)
                    subprocess.check_call('cp -f ' + tmp_save_path + d.template.model.alignment_filename_2 +
                        ' ' + archive_save_path + d.template.model.alignment_filename_2, shell=True)
                # Save the model
                subprocess.check_call('mkdir -p ' + archive_save_path, shell=True)
                subprocess.check_call('cp -f ' + tmp_save_path + d.template.model.model_filename +
                    ' ' + archive_save_path + d.template.model.model_filename, shell=True)
        self.merge_row([d.template, d.template.model])


    def merge_mutation(self, mut, path_to_data=False):
        """
        """
        mut.mut_date_modified = datetime.datetime.utcnow()
        if path_to_data and (mut.model_filename_wt is not None):
            tmp_save_path = self.temp_path + path_to_data
            archive_save_path = self.path_to_archive + path_to_data
            archive_save_subpath = mut.model_filename_wt.split('/')[0] + '/'
            # Save the row corresponding to the mutation as a serialized sqlalchemy object
            subprocess.check_call('mkdir -p ' + archive_save_path + archive_save_subpath, shell=True)
            pickle.dump(dumps(mut), open(archive_save_path + archive_save_subpath + 'mutation.pickle', 'wb'), pickle.HIGHEST_PROTOCOL)
            if mut.model_filename_wt and mut.model_filename_mut:
                # Save Foldx structures
                subprocess.check_call('cp -f ' + tmp_save_path + mut.model_filename_wt +
                                        ' ' + archive_save_path + mut.model_filename_wt, shell=True)
                subprocess.check_call('cp -f ' + tmp_save_path + mut.model_filename_mut +
                                        ' ' + archive_save_path + mut.model_filename_mut, shell=True)
        self.merge_row(mut)


    ###########################################################################

    def get_uniprot_sequence(self, uniprot_id, check_external=False):
        """ Return a Biopython SeqRecord object containg the sequence for the
        specified uniprot.
        """
        with self.session_scope() as session:
            uniprot_sequence = session\
                .query(UniprotSequence)\
                .filter(UniprotSequence.uniprot_id==uniprot_id)\
                .all()

        if len(uniprot_sequence) == 1:
            uniprot_sequence = uniprot_sequence[0]

        elif len(uniprot_sequence) > 1:
            self.logger.error('Type(uniprot_sequence): {}'.format(type(uniprot_sequence)))
            self.logger.error('uniprot_sequence: {}'.format(type(uniprot_sequence)))
            raise Exception('Several uniprot sequences returned!? This should never happen!')

        elif len(uniprot_sequence) == 0:
            username = hf.get_username()
            if (username.strip() == 'joan' # on Scinet
                    or not check_external): # don't bother with external sequences
                print (
                    "Couldn't find a sequence for uniprot {}, and not bothering to look for it online"
                    .format(uniprot_id))
                return None
            else:
                self.logger.debug('Fetching sequence for uniprot {} from an online server'.format(uniprot_id))
                print 'Fetching sequence for uniprot {} from an online server'.format(uniprot_id)
                address = 'http://www.uniprot.org/uniprot/{}.fasta'.format(uniprot_id)
                try:
                    handle = urllib2.urlopen(address)
                    sequence = next(SeqIO.parse(handle, "fasta"))
                except (StopIteration, urllib2.HTTPError) as e:
                    self.logger.debug('{}: {}'.format(type(e), str(e)))
                    print '{}: {}'.format(type(e), str(e))
                    return None
                uniprot_sequence = UniprotSequence()
                uniprot_sequence.uniprot_id = uniprot_id
                sp_or_trembl, uniprot_id_2, uniprot_name = sequence.name.split('|')
                if uniprot_id != uniprot_id_2:
                    print (
                        'Uniprot id of the fasta file ({}) does not match the '
                        'uniprot id of the query ({}). Skipping...'
                        .format(uniprot_id_2, uniprot_id))
                    return None
                uniprot_sequence.db = sp_or_trembl
                uniprot_sequence.uniprot_name = uniprot_name
                uniprot_sequence.uniprot_description = sequence.description
                uniprot_sequence.uniprot_sequence = str(sequence.seq)
                self.add_uniprot_sequence(uniprot_sequence)

        uniprot_seqrecord = SeqIO.SeqRecord(
            seq=Seq.Seq(str(uniprot_sequence.uniprot_sequence)),
            id=uniprot_sequence.uniprot_id,
            name=uniprot_sequence.uniprot_name)

        return uniprot_seqrecord


    def add_uniprot_sequence(self, uniprot_sequence):
        """ Add new sequences to the database.
        :param uniprot_sequence: UniprotSequence object
        :rtype: None
        """
        with self.session_scope() as session:
            session.add(uniprot_sequence)


    ###########################################################################
    def add_domain(self, d):
        with self.session_scope() as session:
            if isinstance(d, Domain):
                session\
                    .query(Domain)\
                    .filter(Domain.cath_id == d.cath_id)\
                    .update({Domain.domain_errors: d.domain_errors})
            elif isinstance(d, DomainContact):
                session\
                    .query(DomainContact)\
                    .filter(DomainContact.domain_contact_id == d.domain_contact_id)\
                    .update({DomainContact.domain_contact_errors: d.domain_contact_errors})


    def add_domain_errors(self, t, error_string):
        with self.session_scope() as session:
            if isinstance(t, UniprotDomain):
                domain = session\
                        .query(Domain)\
                        .filter(Domain.cath_id==t.cath_id)\
                        .as_scalar()
                domain.domain_errors = error_string
                session.merge(domain)
            elif isinstance(t, UniprotDomainPair):
                domain_contact = session\
                    .query(DomainContact)\
                    .filter(DomainContact.cath_id_1==t.cath_id_1)\
                    .filter(DomainContact.cath_id_2==t.cath_id_2)\
                    .all()[0]
                domain_contact.domain_contact_errors = error_string
                session.merge(domain_contact)
            else:
                raise Exception('Wrong type for template!!!')



    ###########################################################################
    def _split_domain(self, domain):
        """
        Takes a string of two domain boundaries and returns a list with int
        The separator is '-' and it can happen that both or one boundary is
        negative, i.e.

            -150-200,   meaning from -150 to 200
            -150--100,  meaning from -150 to -100, etc.

        NOTE! Currently the icode (see Biopython) is disregarded. That means
        that if the numbering is 3B, all '3's are taken. That is the letters
        are stripped! One might want to improve that behaviour.
        """
        # split the domain boundaries, keep eventual minus signs
        if domain[0] == '-' and len(domain[1:].split('-')) == 2:
            domain = ['-' + domain[1:].split('-')[0], domain[1:].split('-')[1]]
        elif domain[0] == '-' and len(domain[1:].split('-')) > 2:
            domain = ['-' + domain[1:].split('-')[0], '-' + domain[1:].split('-')[-1]]
        else:
            domain = [domain.split('-')[0], domain.split('-')[1]]
        # strip the letters
        if domain[0][-1] in uppercase:
            domain[0] = domain[0][:-1]
        if domain[1][-1] in uppercase:
            domain[1] = domain[1][:-1]
        domain = [int(domain[0]), int(domain[1])]
        return domain


    def _split_domain_semicolon(self, domains):
        """ Unlike split_domain(), this function returns a tuple of tuples of strings,
        preserving letter numbering (e.g. 10B)
        """
        x = domains
        return tuple([ tuple([r.strip() for r in ro.split(':')]) for ro in x.split(',') ])


    def _split_interface_aa(self, interface_aa):
        """
        """
        if interface_aa and (interface_aa != '') and (interface_aa != 'NULL'):
            if interface_aa[-1] == ',':
                interface_aa = interface_aa[:-1]

            x  = interface_aa
            return_tuple = tuple([int(r.strip()) for r in x.split(',')])

        else:
            return_tuple = []

        return return_tuple


#    def close(self):
#        if not self.autocommit:
#            self.session.commit()
#        self.session.close()


    ###########################################################################
    def get_alignment(self, model, path_to_data):
        """
        """

        tmp_save_path = self.temp_path + path_to_data
        archive_save_path = self.path_to_archive + path_to_data

        if isinstance(model, UniprotDomainModel):

            # Load previously-calculated alignments
            if os.path.isfile(tmp_save_path + model.alignment_filename):
                alignment = AlignIO.read(tmp_save_path + model.alignment_filename, 'clustal')
            elif os.path.isfile(archive_save_path + model.alignment_filename):
                alignment = AlignIO.read(archive_save_path + model.alignment_filename, 'clustal')
            else:
                raise error.NoPrecalculatedAlignmentFound(archive_save_path, model.alignment_filename)

            return [alignment, None]

        elif isinstance(model, UniprotDomainPairModel):

            # Read alignment from the temporary folder
            if (os.path.isfile(tmp_save_path + model.alignment_filename_1)
            and os.path.isfile(tmp_save_path + model.alignment_filename_2)):
                alignment_1 = AlignIO.read(tmp_save_path + model.alignment_filename_1, 'clustal')
                alignment_2 = AlignIO.read(tmp_save_path + model.alignment_filename_2, 'clustal')
            # Read alignment from the export database
            elif (os.path.isfile(archive_save_path + model.alignment_filename_1)
            and os.path.isfile(archive_save_path + model.alignment_filename_2)):
                alignment_1 = AlignIO.read(archive_save_path + model.alignment_filename_1, 'clustal')
                alignment_2 = AlignIO.read(archive_save_path + model.alignment_filename_2, 'clustal')
            else:
                raise error.NoPrecalculatedAlignmentFound(archive_save_path, model.alignment_filename_1)

            return [alignment_1, alignment_2]


    ###########################################################################
    def load_db_from_csv(self):
        """
        """
        def pd_strip(text):
            # Strip tailing whitespace
            try:
                return text.strip()
            except AttributeError:
                return text

        ## Pupulate sql database from text files
        # Files from while the data will be loaded
        path_to_db = '/home/kimlab1/strokach/working/pipeline/db/'

        domain_infile = path_to_db + 'domain.txt'
        domain_contact_infile = path_to_db + 'domain_contact.txt'
        uniprot_sequence_infile = path_to_db + 'uniprot_sprot_human.txt'
        uniprot_domain_infile = path_to_db + 'uniprot_domain.txt'
        uniprot_domain_pair_infile = path_to_db + 'uniprot_domain_pair.txt'


        # Table `domain`
        names = ['cath_id', 'pdb_id', 'pdb_type', 'pdb_resolution', 'pdb_chain', 'pdb_domain_def', 'pfam_autopfam', 'pfam_name']
        domain_df = pd.read_csv(domain_infile, sep='\t', quoting=1, na_values='\N', names=names, header=None, )
        domain_df['pdb_resolution'] = domain_df['pdb_resolution'].apply(lambda x: float(x))
        domain_df.drop_duplicates(['cath_id',])
        for idx, row in domain_df.iterrows():
            self.session.add(Domain(**row.to_dict()))
            if idx % 10000 == 0:
#                self.session.flush()
                self.logger.debug(idx)
        self.session.commit()
        self.logger.debug('Finished populating table domain')


        # Table `domain_contact`
        names = ['domain_contact_id', 'cath_id_1', 'contact_residues_1', 'cath_id_2', 'contact_residues_2']
        domain_contact_df = pd.read_csv(domain_contact_infile, sep='\t', quoting=1, na_values='\N', names=names, header=None)
        domain_contact_df = domain_contact_df.dropna() # only a couple of rows are droppeds
        for idx, row in domain_contact_df.iterrows():
            self.session.add(DomainContact(**row.to_dict()))
            if idx % 10000 == 0:
#                self.session.flush()
                self.logger.debug(idx)
        self.session.commit()
        self.logger.debug('Finished populating table domain_contact')


        # Table `uniprot_sequence`
        names = ['uniprot_id', 'uniprot_name', 'uniprot_description', 'uniprot_sequence']
        uniprot_sequence_df = pd.read_csv(uniprot_sequence_infile, sep='\t', quoting=1, na_values='\N', names=names, header=None)
        for idx, row in uniprot_sequence_df.iterrows():
            self.session.add(UniprotSequence(**row.to_dict()))
            if idx % 10000 == 0:
#                self.session.flush()
                self.logger.debug(idx)
        self.session.commit()
        self.logger.debug('Finished populating table uniprot_sequence')


        # Table `uniprot_domain`
        if os.path.isfile(uniprot_domain_infile):
#            names = ['uniprot_domain_id', 'uniprot_id', 'pfam_name', 'alignment_def']
            uniprot_domain_df_with_id = pd.read_csv(uniprot_domain_infile, sep='\t', na_values='\N', index_col=False)
            uniprot_domain_df_with_id['alignment_defs'] = uniprot_domain_df_with_id['alignment_def']
            uniprot_domain_df_with_id['alignment_def'] = uniprot_domain_df_with_id['alignment_defs'].apply(lambda x: encode_domain(decode_domain(x)))

            tmp = uniprot_domain_df_with_id.merge(uniprot_sequence_df, how='left', left_on='uniprot_id', right_on='uniprot_id', suffixes=('_domain', ''))
            uniprot_domain_df_with_id['organism_name'] = tmp['uniprot_name'].apply(lambda x: x.split('_')[-1])

            uniprot_domain_df_with_id['path_to_data'] = (
                uniprot_domain_df_with_id['organism_name'].apply(lambda x: x.lower()) + '/' +
                uniprot_domain_df_with_id['uniprot_id'].apply(lambda x: x[0:3]) + '/' +
                uniprot_domain_df_with_id['uniprot_id'].apply(lambda x: x[3:5]) + '/' +
                uniprot_domain_df_with_id['uniprot_id'] + '/' +
                uniprot_domain_df_with_id['pfam_name'] + '*' +
                uniprot_domain_df_with_id['alignment_def'].apply(lambda x: x.replace(':','-')) + '/')

            for idx, row in uniprot_domain_df_with_id.iterrows():
                self.session.add(UniprotDomain(**row.to_dict()))
                if idx % 10000 == 0:
#                    self.session.flush()
                    self.logger.debug(idx)
            self.session.commit()
            self.logger.debug('Finished populating table uniprot_domain')
        else:
            pass
#            pfam_parser = parse_pfamscan.make_uniprot_domain_database()
#            pfam_parser.run()
#            uniprot_domain_df = pfam_parser.get_dataframe()
#            uniprot_domain_df_with_id.to_csv(uniprot_domain_infile, sep='\t', na_rep='\N', index=False)


        # Table `uniprot_domain_pair`
        if os.path.isfile(uniprot_domain_pair_infile):
            uniprot_domain_pair_df_with_id = pd.read_csv(uniprot_domain_pair_infile, sep='\t', na_values='\N', index_col=False)

            temp = uniprot_domain_pair_df_with_id\
                .merge(uniprot_domain_df_with_id, how='left', left_on='uniprot_domain_id_1', right_on='uniprot_domain_id')\
                .merge(uniprot_domain_df_with_id, how='left', left_on='uniprot_domain_id_2', right_on='uniprot_domain_id', suffixes=('_1', '_2'))
            temp['path_to_data'] = (temp['path_to_data_1'] + temp['pfam_name_2'] + '*' + temp['alignment_def_2'].apply(lambda x: x.replace(':','-')) + '/' + temp['uniprot_id_2'] + '/')
            temp = temp[['uniprot_domain_pair_id', 'path_to_data']]
            uniprot_domain_pair_df_with_id = uniprot_domain_pair_df_with_id.merge(temp, how='left')

#            uniprot_domain_pair_df_with_id.to_sql('uniprot_domain_pair', conn, flavor=SQL_FLAVOUR, if_exists='append')
            for idx, row in uniprot_domain_pair_df_with_id.iterrows():
                self.session.add(UniprotDomainPair(**row.to_dict()))
                if idx % 10000 == 0:
#                    self.session.flush()
                    self.logger.debug(idx)
            self.session.commit()
            self.logger.debug('Finished populating table domain')
        else:
            pass
#            pfam_parser = parse_pfamscan.make_uniprot_domain_pair_database(domain_df, domain_contact_df, uniprot_domain_df_with_id,
#                                infile='/home/kimlab1/strokach/working/databases/biogrid/pairs_of_interacting_uniprots_human.tsv')
#            uniprot_domain_pair_df = pfam_parser.get_dataframe()
##            uniprot_domain_pair_df.to_sql('uniprot_domain_pair', conn, flavor=SQL_FLAVOUR, if_exists='append')
##            uniprot_domain_pair_df_with_id = pd.read_sql('SELECT * from uniprot_domain_pair', conn)
#            uniprot_domain_pair_df_with_id.to_csv(uniprot_domain_pair_infile, sep='\t', na_values='\N', index=False)


    def load_db_from_archive(self):
        """
        """
        data = [
            ['human/*/*/*/*/template.json', UniprotDomainTemplate],
            ['human/*/*/*/*/model.json', UniprotDomainModel],
            ['human/*/*/*/*/*/mutation.json', UniprotDomainMutation],
            ['human/*/*/*/*/*/*/template.json', UniprotDomainPairTemplate],
            ['human/*/*/*/*/*/*/model.json', UniprotDomainPairModel],
            ['human/*/*/*/*/*/*/*/mutation.json', UniprotDomainPairMutation],
        ]

        for d in data:
            childProcess = subprocess.Popen('ls ' + self.path_to_archive + d[0], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            result, __ = childProcess.communicate()
            filenames = [fname for fname in result.split('\n') if fname != '']
            for filename in filenames:
                with open(filename, 'r') as fh:
                    row = json.load(fh)
                try:
                    self.session.merge(d[1](**row))
                except TypeError as e:
                    self.logger.debug('Error merging %s.\nProbably from an older version of the database. Skipping...' % filename)
                    self.logger.debug('\t', e)
                self.logger.debug('Merged %s' % filename)
            self.session.commit()
            self.logger.debug('Committed changes\n\n\n')


###############################################################################
if __name__ == '__main__':
#    return
    # run to generate an initial state database (with no precalculatios)
    raise Exception
    print SQL_FLAVOUR
    db = MyDatabase('/home/kimlab1/strokach/working/pipeline/db/pipeline.db',
                    path_to_archive='/home/kimlab1/database_data/elaspic/',
                    SQL_FLAVOUR=SQL_FLAVOUR,
                    clear_database=False)
#    db.load_db_from_csv()
    db.load_db_from_archive()
    db.session.close()
