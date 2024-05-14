from flask import Flask, request, render_template, session, jsonify, redirect, url_for
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


def limpar_arquivos_session():
    diretorio_session = 'flask_session'
    if os.path.exists(diretorio_session):
        shutil.rmtree(diretorio_session)
        print("Arquivos de sessão removidos com sucesso.")
    else:
        print("O diretório de sessão não existe.")


app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'sua_chave_secreta'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
Session(app)

count = 0
instances: Dict[int, ralib.RA] = {}
requisition_queue = queue.Queue()
result_queue = queue.Queue()


def get_relations(string):
    padrao_relations_tuples = r'[A-Z][a-zA-Z]+(?=\()'
    relations_tuples = []
    relation_label = []
    padrao_relations_label = r'[A-Z][a-zA-Z]+\([^)]+\)'
    indice = 0
    while indice < len(string):
        match_encontrado = False
        match = re.search(padrao_relations_label, string[indice:])
        if match:
            relation_label.append(match.group())
            indice += match.end()
            match_encontrado = True
        if not match_encontrado:
            break
    for i in relation_label:
        requisition_queue.put(
            [re.search(padrao_relations_tuples, i).group()+';', session['session_init'], 2])
        relations_tuples.append(result_queue.get())

    for i, item in enumerate(relations_tuples):
        relations_tuples[i] = re.sub(r'\([^)]*\)', '', item)
        relations_tuples[i] = re.sub(r'-+', '', relations_tuples[i])

    return [label + tup for label, tup in zip(relation_label, relations_tuples)], relation_label


def process_db_tasks():
    while True:
        task_data = requisition_queue.get()
        func, user, task = task_data
        if task == 1:
            instances[user] = func
        elif task == 2:
            print(func)
            result = instances[user].executa_consulta_ra(func)
            result_queue.put(result)


db_thread = threading.Thread(target=process_db_tasks)
db_thread.daemon = True
db_thread.start()


def returnqueryUnary(operator, atributes, relation_structured):
    relation = relation_structured
    query = f'\\{operator}{{{atributes}}}({relation})'
    return query


def returnqueryBinary(operator, atributes, relation_structured):
    relation_1, relation_2 = relation_structured
    if atributes is None:
        query = f'({relation_1})\\{operator}({relation_2})'
    else:
        query = f'({relation_1})\\{operator}{{{atributes}}}({relation_2})'
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
        '\u2212': 'intersect',
        '\u2715': 'cross'
    }

    def operatorsthread(operators_clone, index):
        son = operators.pop(index)
        operators_clone.insert(0, son)
        del operators_clone[1]
        return operators_clone

    if len(operators) > 0:
        operator = operators[0]
        atributes_values = operator['atributes_values']
        if operator['operator'] in unary:
            relation_value = operator['relation'][0]
            if isinstance(relation_value, int) and len(operators) != 1:
                for i in range(0, (len(operators) - 1)):
                    if operators[i+1]['operatorindex'] == relation_value:
                        relation_value = CreateConsultfromOperators(
                            operatorsthread(operators, i+1))
                        break
            operator_value = unary.get(operator['operator'])
            query_sufix = returnqueryUnary(
                operator_value, atributes_values, relation_value)
        else:
            relations_values = operator['relation']
            for i in range(0, len(relations_values)):
                if isinstance(relations_values[i], int):
                    for j in range(0, (len(operators) - 1)):
                        if operators[j+1]['operatorindex'] == relations_values[i]:
                            relations_values[i] = CreateConsultfromOperators(
                                operatorsthread(operators, j+1))
                            break
            operator_value = binary.get(operator['operator'])
            query_sufix = returnqueryBinary(
                operator_value, atributes_values, relations_values)

    return query_sufix


@app.route('/home', methods=['GET', 'POST'])
def home():
    global count
    if 'session_init' not in session:
        session['session_init'] = count
        bd_name = request.args.get('bd_name', '')
        requisition_queue.put(
            [ralib.RA(bd_name), session['session_init'], 1])
        requisition_queue.put(
            [f"radb {bd_name}", session['session_init'], 2])
        result_queue.get()
        count += 1
    return render_template('home.html')


@app.route('/consult', methods=['POST'])
async def consult():
    if 'session_init' in session:
        try:
            query = f"{CreateConsultfromOperators(request.get_json())};"
            requisition_queue.put([query, session['session_init'], 2])
            result = result_queue.get()
            return jsonify(result)
        except Exception as e:
            print(e)
            return jsonify({'error': 'Ocorreu um erro durante a consulta'})
    else:
        return jsonify({'error': 'Você precisa definir o banco de dados primeiro!'})


@app.route('/list', methods=['GET'])
def list():
    relations_details_structure = []
    if 'session_init' in session:
        try:
            requisition_queue.put(['\list;', session['session_init'], 2])
            bd, relations_labels = get_relations(result_queue.get())
            for item in relations_labels:
                match = re.match(r'(\w+)\((.*?)\)', item)
                if match:
                    nome_relacao = match.group(1).strip()
                    atributos_str = match.group(2)
                    atributos = [atributo.split(':')[0].strip(
                    ) for atributo in atributos_str.split(',')]
                    relations_details_structure.append(
                        [nome_relacao] + atributos)
            return jsonify(bd, relations_details_structure)
        except Exception as e:
            return jsonify({'erro': e})


@app.route('/loadfile', methods=['GET', 'POST'])
def loadfile():
    if request.method == 'POST':
        file = request.files['file']
        file.save(os.path.join(os.getcwd(), file.filename))
        return redirect(url_for('home', bd_name=file.filename))
    else:
        return render_template('loadfile.html')


atexit.register(limpar_arquivos_session)

if __name__ == '__main__':
    app.run(debug=True)
