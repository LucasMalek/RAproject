import os
import sys
import argparse
import configparser
from radb.db import DB
from radb.typesys import ValTypeChecker
from radb.ast import Context, ValidationError, ExecutionError
from radb.views import ViewCollection
from radb.parse import one_statement_from_string, ParsingError
import getpass
from io import StringIO
import sys

import logging
logger = logging.getLogger('ra')

class RA:
    
    def __init__(self):

        sys_configfile = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), 'sys.ini')
        sys_config = configparser.ConfigParser()
        if sys_config.read(sys_configfile) == []:
            print('ERROR: required system configuration file {} not found'.format(
                sys_configfile))
            sys.exit(1)
        defaults = dict(sys_config.items(configparser.DEFAULTSECT))

        # parse input arguments:
        parser = argparse.ArgumentParser()
        parser.add_argument('--configfile', '-c', type=str, default=defaults['configfile'],
                            help='configuration file (default: {})'.format(defaults['configfile']))
        parser.add_argument('--password', '-p', action='store_true',
                            help='prompt for database password')
        parser.add_argument('--inputfile', '-i', type=str,
                            help='input file')
        parser.add_argument('--outputfile', '-o', type=str,
                            help='output file')
        parser.add_argument('--echo', '-e', action='store_true',
                            help='echo input')
        parser.add_argument('--verbose', '-v', action='store_true',
                            help='verbose output')
        parser.add_argument('--debug', '-d', action='store_true',
                            help='debug output')
        parser.add_argument('source', type=str, nargs='?', default=configparser.DEFAULTSECT,
                            help='data source, which can be the name of a configuration section'
                            ' (default: {}), or otherwise the name of the database to connect to'
                            ' (overriding the configuration default)'.format(configparser.DEFAULTSECT))
        args = parser.parse_args()

        # read user configuration file (starting with system defaults):
        config = configparser.ConfigParser(defaults)
        if config.read(os.path.expanduser(args.configfile)) == []:
            logger.warning('unable to read configuration file {}; resorting to system defaults'
                           .format(os.path.expanduser(args.configfile)))

        # finalize configuration settings, using configuration file and command-line arguments:
        if args.source == configparser.DEFAULTSECT or config.has_section(args.source):
            configured = dict(config.items(args.source))
        else:  # args.source is not a section in the config file; treat it as a database name:
            configured = dict(config.items(configparser.DEFAULTSECT))
            configured['db.database'] = args.source
        if args.password:
            configured['db.password'] = getpass.getpass('Database password: ')

        # connect to database:
        if 'db.database' not in configured:
            logger.warning('no database specified')
        try:
            db = DB(configured)
        except Exception as e:
            logger.error('failed to connect to database: {}'.format(e))
            sys.exit(1)
            
          # Inicializar o sistema de verificação de tipos
        try:
            check = ValTypeChecker(
                configured['default_functions'], configured.get('functions', None))
        except Exception as e:
            print('Failed to initialize type checker:', e)
            sys.exit(1)

        # construct context (starting with empty view collection):
        self.context = Context(configured, db, check, ViewCollection())

    def executa_consulta_ra(self, query):
        output = StringIO()
        sys.stdout = output
        try:
            ast = one_statement_from_string(query)
            logger.info('statement parsed:')
            logger.info(str(ast))
            ast.validate(self.context)
            logger.info('statement validated:')
            ast.execute(self.context)
            return output.getvalue()
        except (ParsingError, ValidationError, ExecutionError) as e:
            print('Error executing query:', e)
        finally:
         sys.stdout = sys.__stdout__