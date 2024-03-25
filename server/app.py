from flask import Flask, request, abort, url_for, redirect, render_template
from ralib import ralib

app = Flask(__name__, static_folder='src')
ra = ralib.RA
secion_cookies = []


@app.route('/home')
def home():
    return render_template('home.html')


@app.route('/consulta', methods=['POST'])
def consulta():
    return ra.executa_consulta_ra(request.form.consulta)


if __name__ == '__main__':
    app.run(debug=True)
