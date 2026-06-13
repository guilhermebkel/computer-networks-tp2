# Programa a ser usado para controlar os roteadores desenvolvidos para o TP2.
# 
# Ele deve ser iniciado com apenas um argumento, que será o nome do arquivo
# contendo a identificação dos roteadores a serem usados.
# Junto com esse código você encontrará os arquivos roteadores_locais.txt
# e roteadores.txt, descritos no arquivo LEIA.ME.
# 
# Para usar o programa com o arquivo de roteadores fornecido, bastaria
# passar o nome do arquivo escolhido como parâmetro.

import socket
import sys
import time

from struct import *  # para pack e unpack

addr = {} # lista de endereços dos roteadores
conn = {} # lista de conexões abertas para cada roteador

def roteadores_ok(roteadores): # confirma se os roteadores existem
    arguments_ok = True
    for roteador in roteadores:
        if roteador not in addr:
            arguments_ok = False
            print("Roteador %s não definido" % (roteador))
    return arguments_ok

# As funções a seguir implementam cada um dos comandos reconhecidos
# Todas elas usam uma ou mais das conexões mantidas na lista conn

#########################################################################
# adiciona_link(argv): comando "A roteador0 roteador1"
# informa o roteador0 que ele deve ser conectar ao roteador1, sendo que 
# o que é enviado ao roteador0 é o nome do host e número do porto usados
# pelo roteador1.
#########################################################################
def adiciona_link(argv):  
    global conn
    roteadores = argv.split(' ')
    if len(roteadores) != 2 or not roteadores_ok(roteadores):
        print("Adiciona link deve ter 2 roteadores validos")
        return
    print("Adicionar link entre",roteadores[0],"e",roteadores[1], end='')
    (rhost,rport) = addr[roteadores[1]]  # endereço do roteador1
    print("(",rhost,",",rport,")")
    msg = pack("!c32sH",'C'.encode(),rhost.encode(),rport)
    conn[roteadores[0]].sendall(msg)
    
#########################################################################
# remove_link(argv): comando "R roteador0 roteador1"
# informa o roteador0 que ele deve terminar a conexão para o roteador1,
# enviando o nome do segundo para o primeiro; a forma como roteador1
# vai tomar conhecimento encerramento do link não é definida aqui.
#########################################################################
def remove_link(argv):
    global conn
    roteadores = argv.split(' ')
    if len(roteadores) != 2 or not roteadores_ok(roteadores):
        print("Remover link deve ter 2 roteadores validos")
        return
    print("Remover link entre",roteadores[0],"e",roteadores[1])
    msg = pack("!c32s",'D'.encode(),roteadores[1].encode())
    conn[roteadores[0]].sendall(msg)

#########################################################################
# mostra_tabela(argv): comando "T roteador"
# comanda o roteador identificado para que ele escreva sua tabela de
# roteamento na sua saída padrão; apenas envia 'T' para o roteador
#########################################################################
def mostra_tabela(argv):
    global conn
    roteador=argv.split(' ')
    if len(roteador)!=1 or not roteadores_ok(roteador):
        print("Mostrar tabela deve ter 1 roteador")
        return
    msg = pack("!c",'T'.encode())
    print("Exibir a tabela no roteador",roteador[0])
    conn[roteador[0]].sendall(msg)

#########################################################################
# inicia_rcrip(argv): comando "I"
# comanda todos os roteadores para que iniciem o protocolo de roteamento;
# apenas envia 'I' para todos os roteadores
#########################################################################
def inicia_rcrip(argv):
    global conn
    if argv!='':
        print("Iniciar RCRIP não espera argumentos")
        return
    msg = pack("!c",'I'.encode())
    print("Enviar I para todos os roteadores")
    for roteador in conn:
        conn[roteador].sendall(msg)

#########################################################################
# envia_texto(argv): comando "E origem destino um texto qualquer"
# comanda o roteador origem para encaminhar a mensagem "um texto qualquer"
# para o roteador destino, usando as rotas determinadas pelo seu protocolo
#########################################################################
def envia_texto(argv):
    global conn
    origem, destino, texto = argv.split(' ',2)
    print("Enviar '%s' para %s a partir de %s" % (texto, destino, origem) )
    if not roteadores_ok((origem,destino)):
        return
    if texto == '':
        print("Texto não fornecido")
        return
    msg = pack("!c32s64s",'E'.encode(),destino.encode(),texto.encode())
    conn[origem].sendall(msg)

#########################################################################
# pausa(argv): comando "P segundos"
# para o programa de controle pelo tempo indicado em segundos; ele será
# usado durante a avaliação para controlar o momento em que cada comando
# será enviado, por exemplo, para esperar as tabelas de roteamento
# estabilizarem após o início do roteamento antes de inspecioná-las
#########################################################################
def pausa(argv):
    tempo=argv.split(' ')
    if len(tempo)!=1 :
        print("Pausar espera tempo em segundos")
        return
    print("ZZ...",end='')
    time.sleep(int(tempo[0]))
    print("00") # abriu os olhos de novo

comandos = {'A': adiciona_link,
           'R': remove_link,
           'T': mostra_tabela,
           'I': inicia_rcrip,
           'E': envia_texto,
           'P': pausa,
}

if len(sys.argv) != 2:
    print("Uso:",sys.argv[0],"nome_arquivo")
    exit(1)

#########################################################################
# Primeiro, o programa lê o arquivo de identificação dos roteadores
# Para cada roteador, estabelece uma conexão que será usada para enviar
# os comandos de controle e envia para o roteador a string com seu nome.
# Essa é a única informação dada ao roteador inicialmente,
# seria como informar o endereço da rede local ao ligá-lo.
# Tudo mais que o roteador precisa saber será informado pelos comandos.
#########################################################################
f = open(sys.argv[1],'r')
roteadores = f.readlines()
for roteador in roteadores:
    rname,rhost,rport_str = roteador.split()
    rport = int(rport_str)
    addr[rname] = (rhost,rport) # monta o dicionário de endereços

    print("conectando",rname,"->",addr[rname],"...", end='', flush=True)
    conn_rot = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn_rot.connect((rhost,rport))
    conn[rname] = conn_rot      # monta o dicionário de conexões
    print(" conectado;", end='', flush=True)

    msg = pack("!32s",rname.encode())
    conn_rot.sendall(msg)       # informa o nome do roteador
    print(" sent \"",rname,"\"",sep='',flush=True)

while(True):
    try:
        line = input()  # lê comandos da entrada padrão
    except EOFError:    # até encontra o fim de arquivo (EOF)
        break
    if line == '':
        continue
    
    ls = line.split(maxsplit=1) # separa o comando
    comando = ls[0]
    argumentos = '' if (len(ls) == 1) else ls[1] 
    comando = comando.rstrip().upper()
    if comando not in comandos:
        print("Comando desconhecido:",comando)
        continue
    comandos[comando](argumentos)

