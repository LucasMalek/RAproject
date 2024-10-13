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

    def __init__(self, db_file_name=None):
        self.db = None  # Atributo da instância para o banco de dados

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
        if db_file_name is not None:
            configured['db.database'] = db_file_name
        try:
            self.db = DB(configured)  # Armazena a conexão no atributo da instância
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
        self.context = Context(configured, self.db, check, ViewCollection())
        
        
    def translate_to_portuguese(self, mensagem_erro):
        if "ParsingError" in mensagem_erro:
            return "Erro de Parsing: Verifique a sintaxe da consulta."
        elif "ValidationError" in mensagem_erro:
            node_start = mensagem_erro.find("in") + 3
            node_end = mensagem_erro.find(":", node_start)
            node = mensagem_erro[node_start:node_end].strip()
            message_start = node_end + 2
            message_end = mensagem_erro.find("context:", message_start)
            if message_end == -1:
                message_end = len(mensagem_erro)
            message = mensagem_erro[message_start:message_end].strip()
            return f"Erro de Validação: {message} no nó {node}."
        elif "ExecutionError" in mensagem_erro:
            return "Erro de Execução: Ocorreu um problema ao executar a consulta."
        else:
            if "invalid attribute reference" in mensagem_erro:
                attribute_start = mensagem_erro.find("in") + 3
                attribute_end = mensagem_erro.find(":", attribute_start)
                attribute_name = mensagem_erro[attribute_start:attribute_end].strip()
                return f"Erro: Referência de atributo: '{attribute_name}'. Verifique se o nome e o valor estão corretos"
            elif "extraneous input" in mensagem_erro:
                return "Erro: Condição incompleta na consulta."
            elif "mismatched input" in mensagem_erro:
                input_start = mensagem_erro.find("input '") + 7
                input_end = mensagem_erro.find("'", input_start)
                invalid_char = mensagem_erro[input_start:input_end].strip()
                return f"Erro: Caractere '{invalid_char}' inválido para o operador específico."
            elif "ambiguous attribute reference" in mensagem_erro:
                attribute_start = mensagem_erro.find("context:") + 9
                attribute_end = mensagem_erro.find(" ", attribute_start)
                attribute_name = mensagem_erro[attribute_start:attribute_end].strip()
                return f"Erro: Referência de atributo ambígua: '{attribute_name}'. No caso de dúvida com o preenchemento da condição, deixe o mouse sobre o botão do operador"
            return f"Erro: {mensagem_erro}"

    def executa_consulta_ra(self, query):
        output = StringIO()
        sys.stdout = output
        error_message = None
        try:
            ast = one_statement_from_string(query)
            logger.info('statement parsed:')
            logger.info(str(ast))
            ast.validate(self.context)
            logger.info('statement validated:')
            ast.execute(self.context)
        except (ParsingError, ValidationError, ExecutionError) as e:
            return self.translate_to_portuguese(str(e))
        finally:
            sys.stdout = sys.__stdout__
        result = output.getvalue()
        if error_message:
            result += f"\n{error_message}"
        
        return result

    def close_db(self):
        """Método para fechar a conexão com o banco de dados"""
        if self.db and self.db.conn:
            self.db.conn.close()
            self.db.engine.dispose()
            self.db = None
            
