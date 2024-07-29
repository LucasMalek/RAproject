from flask import Flask, request, render_template, session, jsonify, url_for
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
from werkzeug.datastructures import FileStorage
import requests 


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
        task_data = requisition_queue.get()
        func, user, task = task_data
        if task == 1:
            instances[user] = func
        elif task == 2:
            result = instances[user].executa_consulta_ra(func)
            result_queue.put(result)


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
            query.append(f'({rel1_toquery})\\{operator}({rel2_toquery})')
        else:
            query.append(f'({rel1_toquery})\\{operator}{{{atributes}}}({rel2_toquery})')
                  
        query.append(format_binary_query(rel1_toshow, rel1_toshow))
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

            

def CreateConsultfromOperators(operators):
    query_sufix = ''
    unary = {
        '\u03C3': 'select_',
        '\u03C0': 'project_',
        '\u03C1': 'rename_'
    }
    binary = {
        '\u222A': 'union',
        '\u2212': 'diff',
        '\u2229': 'intersect',
        '\u2715': 'cross'
    }

    def operatorsthread(operators_clone, index):
        son = operators.pop(index)
        operators_clone.insert(0, son)
        del operators_clone[1]
        return operators_clone

    if len(operators) > 0:
        operator = operators[0]
        operator_caractere = operator['operator'] 
        if operator_caractere in unary:
            atributes_values = operator['atributes_values']
            relation_value = operator['relation'][0]
            if isinstance(relation_value, int) and len(operators) != 1:
                for i in range(0, (len(operators) - 1)):
                    if operators[i+1]['operatorindex'] == relation_value:
                        relation_value = CreateConsultfromOperators(
                            operatorsthread(operators, i+1))
                        break
            operator_value = unary.get(operator_caractere)
            query_sufix = returnqueryUnary(
                operator_value, atributes_values, relation_value, operator_caractere)
        else:
            relations_values = operator['relation']
            atributes_values = operator['atributes_values']
            for i in range(0, len(relations_values)):
                if isinstance(relations_values[i], int):
                    for j in range(0, (len(operators) - 1)):
                        if operators[j+1]['operatorindex'] == relations_values[i]:
                            relations_values[i] = CreateConsultfromOperators(
                                operatorsthread(operators, j+1))
                            break
            operator_value = binary.get(operator_caractere)
            query_sufix = returnqueryBinary(
                operator_value, atributes_values, relations_values, operator_caractere)
       
    return query_sufix


@app.route('/consult', methods=['POST'])
async def consult():
    if 'session_init' in session:
        try:
            consult_complete = CreateConsultfromOperators(request.get_json())
            query = f"{consult_complete[0]};"
            requisition_queue.put([query, session['session_init'], 2])
            result = result_queue.get()
            result_formated = reform_consult(result)
            return jsonify(result_formated, consult_complete[1])
        except Exception as e:
            print(e)
            return jsonify({'error': 'Ocorreu um erro durante a consulta'})
    else:
        return jsonify({'error': 'Você precisa definir o banco de dados primeiro!'})


@app.route('/loadfile', methods=['GET', 'POST'])
def loadfile():
    if 'session_init' not in session:
        global count
        session['session_init'] = count
        relations_details_structure = []
        file = request.files['file']
        bd_name = f"{str(session['session_init'])}.db"
        file.save(os.path.join(os.getcwd(), bd_name))
        requisition_queue.put(
            [ralib.RA(bd_name), session['session_init'], 1])
        requisition_queue.put(
            [f"radb {bd_name}", session['session_init'], 2])
        result_queue.get()
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
                    atributos = [atributo.strip()
                                 for atributo in atributos_str.split(',')]
                    relations_details_structure.append(
                        [nome_relacao] + atributos)
            return jsonify([tuples, relations_details_structure])
        except Exception as e:
            return jsonify({'erro': e})


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
def createdbfile():
    if 'session_init' not in session:
        global count
        session['session_init'] = count
        relations_details_structure = []
        conn = sqlite3.connect(f"{str(session['session_init'])}.db")
        cursor = conn.cursor()
        db = request.get_json()
        for table, info in db.items():
            tablename = info["tablename"]
            attr_types = ", ".join([f"{attribute} {typ}" for attribute, typ in zip(
                info["attributes"], info["types"])])
            cursor.execute(f"CREATE TABLE {tablename} ({attr_types})")
            for tuple in info["tuples"]:
                placeholders = ", ".join(["?"] * len(tuple))
                cursor.execute(
                    f"INSERT INTO {tablename} VALUES ({placeholders})", tuple)
        conn.commit()
        conn.close()
        bd_name = f"{str(session['session_init'])}.db"
        requisition_queue.put(
            [ralib.RA(bd_name), session['session_init'], 1])
        requisition_queue.put(
            [f"radb {bd_name}", session['session_init'], 2])
        result_queue.get()
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
                    atributos = [atributo.strip()
                                 for atributo in atributos_str.split(',')]
                    relations_details_structure.append(
                        [nome_relacao] + atributos)
            return jsonify([tuples, relations_details_structure])
        except Exception as e:
            return jsonify({'erro': e})
  

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
        
     
atexit.register(limpar_arquivos_session)
atexit.register(clean_db_files)

if __name__ == '__main__':
    app.run(debug=True)
