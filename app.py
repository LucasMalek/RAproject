from flask import Flask, request, render_template, session, jsonify
from flask_session import Session
import queue
import threading
from typing import Dict
from ralib import ralib
import re

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'sua_chave_secreta'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
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
              requisition_queue.put([re.search(padrao_relations_tuples, i).group()+';', session['session_init'], 2])
              relations_tuples.append(result_queue.get())
              
    for i, item in enumerate(relations_tuples):
        relations_tuples[i] = re.sub(r'\([^)]*\)', '', item)  
        relations_tuples[i] = re.sub(r'-+', '', relations_tuples[i])  
        
    return [label + tup for label, tup in zip(relation_label, relations_tuples)]

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

@app.route('/home')
def home():
    global count
    session.clear()
    if 'session_init' not in session:
        session['session_init'] = count
        requisition_queue.put([ralib.RA(), session['session_init'], 1])
        requisition_queue.put(["\source 'beers.ra';", session['session_init'], 2])
        result_queue.get()
        count += 1
    return render_template('home.html')

@app.route('/consult', methods=['POST'])
async def consult():
    if 'session_init' in session:
        try:
            query = request.form['consult_input']
            query = f'{query};'
            requisition_queue.put([query, session['session_init'], 2])
            result = result_queue.get()
            return jsonify(result)
        except Exception as e:
            print(e)
            return jsonify({'error': 'Ocorreu um erro durante a consulta'})
    else:
        return jsonify({'error': 'Você precisa definir o banco de dados primeiro!'})
    
@app.route('/list', methods = ['GET'])
def list():
    if 'session_init' in session:
        try:
          requisition_queue.put(['\list;', session['session_init'], 2])
          resultado = get_relations(result_queue.get())
          return jsonify(resultado)
        except Exception as e:
            return jsonify({'erro': e})

if __name__ == '__main__':
    app.run(debug=True)
