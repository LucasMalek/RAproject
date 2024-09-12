from flask import Flask, request, render_template, session, jsonify, make_response ,redirect, url_for
from flask_session import Session
import queue
import threading
from typing import Dict
from ralib import ralib
import re
import atexit
import os
import shutil
from datetime import timedelta
import glob
import sqlite3
from io import BytesIO
import time
import queue
from collections import Counter


def limpar_arquivos_session():
    diretorio_session = 'flask_session'
    if os.path.exists(diretorio_session):
        shutil.rmtree(diretorio_session)
        print("Arquivos de sessão removidos com sucesso.")
    else:
        print("O diretório de sessão não existe.")


def clean_db_files():
    files = glob.glob('*.db')
    for file in files:
        try:
            os.remove(file)
        except OSError as e:
            print(e)


app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'sua_chave_secreta'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
Session(app)

count = 0
instances: Dict[int, ralib.RA] = {}
requisition_queue = queue.Queue()
result_queue = queue.Queue()


def reform_list(string, requisition):
    padrao_relations_tuples = r'[^\s]*(?=\()'
    padrao_relations_label = r'[^\s]*\([^)]+\)'
    relations_tuples = []
    relation_label = []
    indice = 0
    
    while indice < len(string):
        match_encontrado = False
        match = re.search(padrao_relations_label, string[indice:])
        if match:
            identified = match.group()
            if requisition != 'list':
               if requisition in identified:
                    relation_label.append(identified)
                    break
               else: 
                indice += match.end()
                match_encontrado = True
            else:
                relation_label.append(identified)
                indice += match.end()
                match_encontrado = True
        if not match_encontrado:
            break
        
    for i in relation_label:
            requisition_queue.put(
                [re.search(padrao_relations_tuples, i).group()+';', session['session_init'], 2])
            relations_tuples.append(result_queue.get())
            
    for i, item in enumerate(relations_tuples):
        lines = item.strip().splitlines()
        padrao = re.compile(r'^\s*[^,]+(?:,\s*[^,]+)*\s*$')
        tuplas = []
        for line in lines[1:]:
            if not line.startswith('-') and 'tuple returned' not in line:
                if padrao.match(line):
                    parts = [part.strip() for part in line.split(',')]
                    tupla = tuple(parts)
                    tuplas.append(tupla)
        relations_tuples[i] = tuplas
    
    return relation_label, relations_tuples


def reform_consult(string):
    pattern_labels = re.compile(r'\((.*?)\)')
    pattern_tuples = re.compile(r'^\s*([^\-].*?)\s*$', re.MULTILINE)
    
    labels = []
    tuples = []
    
    reformed_result = []

    match_labels = re.search(pattern_labels, string)
    if match_labels:
        labels = match_labels.group(1).split(', ')
        index = match_labels.end()
        
    match_tuples = re.findall(pattern_tuples, string[index:])
    for match in match_tuples:
        line = match.strip()
        if line and not line.startswith('-') and not re.match(r'^\d+ tuple(s)? returned', line):
            tuples.append(line.split(', '))
    
    reformed_result = labels, tuples
    
    return reformed_result


def process_db_tasks():
    while True:
        try:
            task_data = requisition_queue.get(timeout=2) 
            func, user, task = task_data
            if task == 1:
                instances[user] = func 
            elif task == 2:
                result = instances[user].executa_consulta_ra(func)
                result_queue.put(result)
            else:
                instances[user].close_db()
        except queue.Empty:
            pass
        except Exception as e:
            pass
        time.sleep(0.2)  

db_thread = threading.Thread(target=process_db_tasks)
db_thread.daemon = True
db_thread.start()


def returnqueryUnary(operator, atributes, relation_structured, operator_code):
    
    def format_unary_html(operator_code, attributes, relation):
        formatted_query = (
            f'<span class = "text_query_operator">{operator_code}</span>'
            f'<span class = "text_query_attributes">{{{attributes}}}</span>'
            f'<span class = "text_query_parentheses">(</span><span class= "text_query_relation">{relation}</span><span class = "text_query_parentheses">)</span>'
        )
        return formatted_query
    
    query = []
    if(isinstance(relation_structured, str)):
        query.append(f'\\{operator}{{{atributes}}}({relation_structured})')
        query.append(format_unary_html(operator_code, atributes, relation_structured))
    else:
        query.append(f'\\{operator}{{{atributes}}}({relation_structured[0]})')
        query.append(format_unary_html(operator_code, atributes, relation_structured[1]))
    return query

def returnqueryBinary(operator, atributes, relation_structured, operator_code):
    query = []
    relation_1, relation_2 = relation_structured
    
    def format_binary_query(rel1, rel2):
        if atributes:
            formatted_query = (
                f'<span class = "text_query_parentheses">(</span><span class= "text_query_relation">{rel1}</span><span class = "text_query_parentheses">)</span>'
                f'<span class="text_query_operator" style="font-size: 1.5rem !important;">{operator_code}</span>'
                f'<span class = "text_query_attributes">{{{atributes}}}</span>'
                f'<span class = "text_query_parentheses">(</span><span class= "text_query_relation">{rel2}</span><span class = "text_query_parentheses">)</span>'
            )
        else:
            formatted_query = (
                f'<span class = "text_query_parentheses">(</span><span class= "text_query_relation">{rel1}</span><span class = "text_query_parentheses">)</span>'
                f'<span class = "text_query_operator" style="font-size: 1.8rem;">{operator_code}</span>'
                f'<span class = "text_query_parentheses">(</span><span class= "text_query_relation">{rel2}</span><span class = "text_query_parentheses">)</span>'
            )
        return formatted_query

    def append_queries(rel1_toquery, rel2_toquery, rel1_toshow, rel2_toshow):
        if atributes is None:
            if operator == 'assigment':
                query.append(rel2_toquery)
            else:
                 query.append(f'({rel1_toquery})\\{operator}({rel2_toquery})')
        else:
            query.append(f'({rel1_toquery})\\{operator}{{{atributes}}}({rel2_toquery})')
                  
        query.append(format_binary_query(rel1_toshow, rel2_toshow))
        return query

    if isinstance(relation_1, str) and isinstance(relation_2, str):
        return append_queries(relation_1, relation_2, relation_1, relation_2)
    if isinstance(relation_1, list) and isinstance(relation_2, list):
        return append_queries(relation_1[0], relation_2[0], relation_1[1], relation_2[1]) 
    if isinstance(relation_1, list) and isinstance(relation_2, str):
        return append_queries(relation_1[0], relation_2, relation_1[1], relation_2) 
    if isinstance(relation_1, str) and isinstance(relation_2, list):
        return append_queries(relation_1, relation_2[0], relation_1, relation_2[1])

    return query

def validateattributes(attributes, type):
  
  if not attributes:
      return "A expressão de atributos não pode estar vazia!"  
    
  if type == 'attribute+value':
     pattern = r'^(\s*\w+\s*=\s*[^,]+)(\s*,\s*\w+\s*=\s*[^,]+)*\s*$'
     match = re.match(pattern, attributes)
     if match:
        return True, None
     else:
        if not re.search(r'\w+\s*=\s*\w+', attributes):
            return "Erro: Nenhum par 'atributo = valor' encontrado."
        
        if re.search(r'\w+\s*=\s*\w+,\s*\w+\s*=\s*$', attributes):
            return "Erro: Vírgula extra no final."
        
        if re.search(r'\w+\s*=\s*[^,]*$', attributes):
            return "Erro: Atributo ou valor ausente após '='"
        
        if re.search(r'\w+\s*=\s*\w+[^,]\s*$', attributes):
            return "Erro: Faltando vírgula entre pares de 'atributo = valor'."
        
        return False, 'Formato inválido. Use "atributo = valor" e se necessário separe múltiplos pares com vírgulas.'
     
  elif type == 'attribute':        
     pattern = r'^(\s*\w+\s*)(\s*,\s*\w+\s*)*$'
     match = re.match(pattern, attributes)
     if match:
        return True, None
     else:
        if re.search(r',\s*$', attributes):
         return "Erro: Vírgula extra no final."
        
        return False, 'Formato inválido. Use "atributo1, atributo2..." ou apenas "atributo". Lembre-se, caso tenha mais de um atributo, use apenas uma vírgula entre eles!'

def CreateConsultfromOperators(operators, assigments = None):
    query_sufix = ''
    unary = {
        '\u03C3': 'select_',
        '\u03C0': 'project_',
        '\u03C1': 'rename_',  
    }
    binary = {
        '\u222A': 'union',
        '\u2212': 'diff',
        '\u2229': 'intersect',
        '\u2715': 'cross',
        '\u2190': 'assigment',
        '⋈': 'join',
        '⋈θ': 'join_'
    }

    def operatorsthread(operators_clone, index):
        son = operators.pop(index)
        operators_clone.insert(0, son)
        del operators_clone[1]
        return operators_clone

    if len(operators) > 0:
        operator = operators[0]
        operator_caractere = operator['operator']
        atributes_values = operator['atributes_values']
        if operator_caractere in unary:
            relation_value = operator['relation'][0]
            operator_value = unary.get(operator_caractere)
            if isinstance(relation_value, int) and len(operators) != 1:
                for i in range(0, (len(operators) - 1)):
                    if operators[i+1]['operatorindex'] == relation_value:
                        relation_value = CreateConsultfromOperators(
                            operatorsthread(operators, i+1), assigments)
                        break
                    
            if isinstance(relation_value, str):
                relation_formulated = assigments.get(relation_value, False)
                if relation_formulated !=  False:
                    relation_value = relation_formulated
                else:
                    return ['error', f"Relação {relation_value} não existe!"]
                
            query_sufix = returnqueryUnary(
                operator_value, atributes_values, relation_value, operator_caractere)
        else:
            relations_values = operator['relation']
            for i in range(0, len(relations_values)):
                if isinstance(relations_values[i], int):
                    for j in range(0, (len(operators) - 1)):
                        if operators[j+1]['operatorindex'] == relations_values[i]:
                            relations_values[i] = CreateConsultfromOperators(
                                operatorsthread(operators, j+1), assigments)
                            break
                if isinstance(relations_values[i], str):
                    if not operator_caractere == '\u2190' or operator_caractere == '\u2190' and i != 0:
                        relation_formulated = assigments.get(relations_values[i], False)
                        if relation_formulated !=  False:
                            relations_values[i] = relation_formulated
                        else:
                            return ['error', f"Relação {relations_values[i]} não existe!"]
                   
            operator_value = binary.get(operator_caractere)
            query_sufix = returnqueryBinary(
                operator_value, atributes_values, relations_values, operator_caractere)
       
    return query_sufix


@app.route('/consult', methods=['POST'])
async def consult():
    if 'session_init' in session:
        try:
            assigments : Dict[str: str] = {}
            consult_lines, tablenames = request.get_json()
            consult_complete = []
            all_results = []
            
            for table in tablenames:
                assigments[table] = table
                                    
            for index, consult in enumerate(consult_lines):
                intermediate_response = []
                if isinstance(consult[0], str):
                    intermediate_response = CreateConsultfromOperators(consult[1:], assigments)
                    if(intermediate_response[0] != 'error'):
                     assigments[consult[0]] = intermediate_response
                    else:
                        return make_response(jsonify({'error': f"Linha {index + 1}: {intermediate_response[1]}"}), 400)
                else:
                  intermediate_response = CreateConsultfromOperators(consult, assigments)
                  if(intermediate_response[0] != 'error'):  
                   consult_complete.append(intermediate_response)
                  else:
                    return make_response(jsonify({'error': f"Linha {index + 1}: {intermediate_response[1]}"}), 400)  
                  
            
            for table in tablenames:
                assigments.pop(table)
                
            consult_complete.extend([valor for valor in assigments.values()])
            
            for index, consult in enumerate(consult_complete):
                query = f"{consult[0]};"
                requisition_queue.put([query, session['session_init'], 2])
                result = result_queue.get()
                if 'no tuples returned' in result:
                    all_results.append(['Nenhuma tupla retornada. Verifique a consulta novamente.', consult[1]])
                    continue
                error_pattern = re.compile(r'Erro[^:]*:')
                match = re.search(error_pattern, result)
                if match:
                    return make_response(jsonify({'error': f"Linha {index + 1}: {result}"}), 500)
                all_results.append([reform_consult(result), consult[1]])
            
            return jsonify(all_results)
        
        except Exception as e:
            print(e)
            return make_response(jsonify({'error': 'Ocorreu um erro durante a consulta'}), 500)
    else:
         return make_response(jsonify({'error': 'Você precisa definir o banco de dados primeiro!'}), 400)


@app.route('/loadfile', methods=['GET', 'POST'])
def loadfile(file=None):
    global count, instances
    if 'session_init' not in session:
        session['session_init'] = count
        session['page_visited'] = True 
        relations_details_structure = []
        
        if file is None:
            if 'file' not in request.files:
                return jsonify({'erro': 'Nenhum arquivo foi enviado!'}), 400
            file = request.files['file']
        
        bd_name = f"{str(session['session_init'])}.db"
        file.save(os.path.join(os.getcwd(), bd_name))
        
        requisition_queue.put([ralib.RA(bd_name), session['session_init'], 1])

        requisition_queue.put([f"radb {bd_name}", session['session_init'], 2])
        
        result = result_queue.get()
        
        count += 1
        
        try:
            requisition_queue.put(['\list;', session['session_init'], 2])
            result = result_queue.get()
            
            relations_labels, tuples = reform_list(result, 'list')
            
            for item in relations_labels:
                match = re.match(r'(\w+)\((.*?)\)', item)
                if match:
                    nome_relacao = match.group(1).strip()
                    atributos_str = match.group(2)
                    atributos = [atributo.strip() for atributo in atributos_str.split(',')]
                    relations_details_structure.append([nome_relacao] + atributos)
            
            return jsonify([tuples, relations_details_structure])
        except Exception as e:
            return jsonify({'erro': str(e)}), 500

@app.route('/prototipo', methods=['GET'])
def prototipo():
    return render_template('prototipohome.html')


@app.route('/colectinfofromtable', methods=['POST'])
def colectinfofromtable():
    if 'session_init' in session:
        requisition = request.get_json()
        tablename = requisition['tablename']
        conn = sqlite3.connect(f"{str(session['session_init'])}.db")
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({tablename})")
        rows = cursor.fetchall()
        columns = [row[1] for row in rows]
        types = [row[2] for row in rows]
        info = {}
        if(requisition['type'] == 'includetuples'):
            cursor.execute(f"SELECT * FROM {tablename}")
            tuples = cursor.fetchall()
            info = {
                "attributes": columns,
                "types": types,
                "tuples": tuples
            }
        else:
            info = {
                "attributes": columns,
                "types": types
            }
        return jsonify(info)


@app.route('/insert', methods=['POST'])
def insert():
    if 'session_init' in session:
        try:
            tablename = ''
            relations_details_structure = []
            conn = sqlite3.connect(f"{str(session['session_init'])}.db")
            cursor = conn.cursor()
            tuples = request.get_json()
            for table, info in tuples.items():
                tablename = info['tablename']
                for tuple in info["tuples"]:
                    placeholders = ", ".join(["?"] * len(tuple))
                    cursor.execute(
                        f"INSERT INTO {tablename} VALUES ({placeholders})", tuple
                    )
            conn.commit()
            conn.close()
            requisition_queue.put([f"radb {str(session['session_init'])}.db", session['session_init'], 2])
            result_queue.get()
            requisition_queue.put(['\list;', session['session_init'], 2])
            result = result_queue.get()
            relations_labels, tuples = reform_list(result, tablename)
            for item in relations_labels:
                match = re.match(r'(\w+)\((.*?)\)', item)
                if match:
                    nome_relacao = match.group(1).strip()
                    atributos_str = match.group(2)
                    atributos = [atributo.strip() for atributo in atributos_str.split(',')]
                    relations_details_structure.append([nome_relacao] + atributos)

            return jsonify([tuples, relations_details_structure])

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:
        return jsonify({'error': 'Session not initialized'}), 400

@app.route('/createdbfile', methods=['POST'])
def createdbfile(db=None):
    global count
    if 'session_init' not in session:
        session['session_init'] = count
        session['page_visited'] = True 

    relations_details_structure = []
    
    try:
        if db is None:
            db = request.get_json()
        
        tablenames = []
        for table, info in db.items():
            tablename = info["tablename"]
            attributes = info["attributes"]
            
            # Verifica se o nome da tabela foi usado mais de uma vez
            if tablename in tablenames:
                raise ValueError(f"O Nome {tablename} foi utilizado mais de uma vez para tabelas diferentes")
            
            tablenames.append(tablename)

            # Verifica se há atributos repetidos
            verify = Counter(attributes)
            rep = [item for item, freq in verify.items() if freq > 1]
            if len(rep) > 0:
                raise ValueError(f"Atributo(s) repetido(s): {', '.join(rep)}")

    except Exception as e:
        # Limpa a sessão se houver algum erro nas verificações
        session.clear()
        return make_response(jsonify({'error': str(e)}), 400)
    
    # Segunda etapa: Criar o banco de dados e inserir as tabelas/dados
    bd_name = f"{str(session['session_init'])}.db"
    
    try:
        conn = sqlite3.connect(bd_name)
        cursor = conn.cursor()

        for table, info in db.items():
            tablename = info["tablename"]
            attributes = info["attributes"]
            types = info["types"]

            # Cria a tabela
            attr_types = ", ".join([f"{attribute} {typ}" for attribute, typ in zip(attributes, types)])
            cursor.execute(f"CREATE TABLE {tablename} ({attr_types})")

            # Insere os dados
            for tuple_values in info["tuples"]:
                placeholders = ", ".join(["?"] * len(tuple_values))
                cursor.execute(f"INSERT INTO {tablename} VALUES ({placeholders})", tuple_values)

        conn.commit()
        conn.close()

        # Processa os dados
        requisition_queue.put([ralib.RA(bd_name), session['session_init'], 1])
        requisition_queue.put([f"radb {bd_name}", session['session_init'], 2])
        result_queue.get()
        count += 1

        # Obter as relações e retornar
        requisition_queue.put(['\list;', session['session_init'], 2])
        result = result_queue.get()
        relations_labels, tuples = reform_list(result, 'list')

        for item in relations_labels:
            match = re.match(r'(\w+)\((.*?)\)', item)
            if match:
                nome_relacao = match.group(1).strip()
                atributos_str = match.group(2)
                atributos = [atributo.strip() for atributo in atributos_str.split(',')]
                relations_details_structure.append([nome_relacao] + atributos)

        return jsonify([tuples, relations_details_structure])

    except Exception as e:
        session.clear()
        return make_response(jsonify({'error': str(e)}), 500)

@app.route('/deletetable', methods = ['POST'])
def deletetable():
     if 'session_init' in session:
        conn = sqlite3.connect(f"{str(session['session_init'])}.db")
        cursor = conn.cursor()
        tablename = request.get_json()['tablename']
        cursor.execute(f"DROP TABLE IF EXISTS {tablename}")
        conn.commit()
        conn.close()
        return 'ok', 200
    

@app.route('/update', methods=['POST'])
def update():
    if 'session_init' in session:
        data = request.get_json()
        tablename = data['1']['tablename']
        relations_details_structure = []
        conn = sqlite3.connect(f"{str(session['session_init'])}.db")
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {tablename}")
        for table, info in data.items():
                for tuple in info["tuples"]:
                    placeholders = ", ".join(["?"] * len(tuple))
                    cursor.execute(
                        f"INSERT INTO {tablename} VALUES ({placeholders})", tuple
                    )
        conn.commit()
        conn.close()
        requisition_queue.put([f"radb {str(session['session_init'])}.db", session['session_init'], 2])
        result_queue.get()
        requisition_queue.put(['\list;', session['session_init'], 2])
        result = result_queue.get()
        relations_labels, tuples = reform_list(result, tablename)
        for item in relations_labels:
            match = re.match(r'(\w+)\((.*?)\)', item)
            if match:
                nome_relacao = match.group(1).strip()
                atributos_str = match.group(2)
                atributos = [atributo.strip() for atributo in atributos_str.split(',')]
                relations_details_structure.append([nome_relacao] + atributos)

        return jsonify([tuples, relations_details_structure])


@app.route('/deletetuple', methods = ['POST'])
def deletetuple():
     if 'session_init' in session:
        try:
            conn = sqlite3.connect(f"{str(session['session_init'])}.db")
            cursor = conn.cursor()
            db =  request.get_json()
            tablename = db['tablename']
            relations_details_structure = []
            tuples = db['tuples_to_delete']
            for tuple_to_delete in tuples:
                conditions = " AND ".join([f"{attribute} = ?" for attribute, value in tuple_to_delete])
                values = [value for attribute, value in tuple_to_delete]
                query = f"DELETE FROM {tablename} WHERE {conditions}"
                cursor.execute(query, values)
            conn.commit()
            conn.close()
            requisition_queue.put([f"radb {str(session['session_init'])}.db", session['session_init'], 2])
            result_queue.get()
            requisition_queue.put(['\list;', session['session_init'], 2])
            result = result_queue.get()
            relations_labels, tuples = reform_list(result, tablename)
            for item in relations_labels:
                    match = re.match(r'(\w+)\((.*?)\)', item)
                    if match:
                        nome_relacao = match.group(1).strip()
                        atributos_str = match.group(2)
                        atributos = [atributo.strip() for atributo in atributos_str.split(',')]
                        relations_details_structure.append([nome_relacao] + atributos)

            return jsonify([tuples, relations_details_structure])

        except Exception as e:
            return jsonify({'error': str(e)}), 500

     else:
            return jsonify({'error': 'Session not initialized'}), 400
  
  
def delete_user_archive(archive_name):
    archive = f"{str(archive_name)}.db"
    if os.path.exists(archive):
        try:
            os.remove(archive)
        except OSError as e:
            print(f"Erro ao tentar apagar o arquivo '{archive_name}': {e}")
    else:
        return
    return    

@app.route('/logout', methods=['POST'])
def logout():
     if 'page_visited' in session:
        user_number = session['session_init']
        requisition_queue.put([None, user_number, 3])
        requisition_queue.put(['\quit;', user_number, 2])
        time.sleep(0.2)
        instances.pop(user_number, None) 
        delete_user_archive(user_number)
        session.clear() 
     return '', 204   

atexit.register(limpar_arquivos_session)
atexit.register(clean_db_files)

if __name__ == '__main__':
    app.run(debug=True)
