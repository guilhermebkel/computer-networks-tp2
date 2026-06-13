# Autores: Guilherme Mota Bromonschenkel Lima e Flavio Gabriel Soares Melo

# Este é um programa simples que mostra como receber as mensagens enviadas
# pelo programa de controle do TP2, até para confirmar que ele está
# enviando as mensagens corretamente. 
# Ele espera receber como parâmetro o porto onde deve receber as mensagens.
# Tudo mais que um roteador precisaria para operar seria fornecido pelos
# comandos definidos no enunciado do TP.

import socket
import sys
from struct import *

####################################################################
# Essas funções fazem a separação dos campos da mensagem recebida.
####################################################################

def extrai_roteador(msg):
    r = unpack("!32s",msg) # 32 caracteres com o nome de um roteador
    return r[0].decode()

def extrai_endereco(msg):
    r = unpack("!32sH",msg) # 32 caracteres com o host e short int com o porto
    return r[0].decode(), r[1]

def extrai_destino_texto(msg):
    l = unpack(">32s64s",msg) # 32 caracteres com o nome de um roteador
                              # e uma mensagem com 64 caracteres
    destino = l[0].decode()
    texto   = l[1].decode()
    return destino, texto

####################################################################
# Início do programa: aguarda a conexão do programa de controle
####################################################################
print("I am here", end='', flush=True)
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# SO_REUSEADDR evita o erro temporário "address already in use" que 
# pode aparecer em alguns casos quando um servidor termina de forma anormal

# depois de criar o socket, faz o bind, listen e acept da primeira conexão
server_port = int(sys.argv[1])
server_socket.bind(('',server_port))
server_socket.listen()
print(" at port",server_port, end='', flush=True)
control, ctrl_addr = server_socket.accept()

# espera o nome do roteador enviado pelo programa de controle
print(" my name is ", end='', flush=True)
my_name_msg = b''
my_name_msg = control.recv(32);
l = unpack("!32s",my_name_msg)
my_name = l[0].decode()
print(my_name,flush=True)


####################################################################
# a partir deste ponto, certamente seu programa precisará ser alterado
# para incluir o uso do select para observar as conexões existentes e
# novas que surjam de outros roteadores, bem como enviar periodicamente
# as mensagens do protocolo de roteamento para os seus vizinhos imediados
####################################################################

import select
import threading

lock = threading.Lock()
sockets_list = []
routing_table = {}
peer_router_name_to_socket = {}

def recv_exactly(sock, expected_bytes):
    received = b''
    while len(received) < expected_bytes:
        remaining = expected_bytes - len(received)
        chunk = sock.recv(remaining)
        if not chunk:
            return b''
        received += chunk
    return received

def pack_router_name(name):
    return name.encode('ascii', errors='replace')[:32].ljust(32, b'\x00')

def unpack_router_name(data):
    return data.rstrip(b'\x00').decode('ascii', errors='replace')

while(True):  # aguarda mensagens do comando de controle
    try:
        readable, _, _ = select.select(sockets_list, [], [])
    except (ValueError, OSError):
        break

    for socket in list(readable):
        # novas conexões de roteadores vizinhos
        if socket is server_socket:
            connection, _ = server_socket.accept()
            peer_router_name_in_bytes = recv_exactly(connection, 32)

            if not peer_router_name_in_bytes:
                connection.close()
                continue

            peer_router_name = unpack_router_name(peer_router_name_in_bytes)

            # enviamos o nome do nosso roteador de volta
            connection.sendall(pack_router_name(my_name))

            with lock:
                if peer_router_name in peer_router_name_to_socket:
                    # evitamos uma nova conexão com esse vizinho caso ela já existir
                    connection.close()
                else:
                    peer_router_name_to_socket[peer_router_name] = connection
                    routing_table[peer_router_name] = (peer_router_name, 1)
                    sockets_list.append(connection)

        # mensagens do programa de controle
        elif socket is control:
            msg = control.recv(1)   # no roteador, não haverá apenas essa conexão
            if not msg or msg=='':
                print("Connection closed",flush=True)
                sys.exit()
            c = unpack("!c",msg)
            comando = c[0].decode()

            if comando=='C':
                # o roteador recebe o ENDEREÇO do outro roteador ao qual se conectar
                msg=control.recv(34)
                host, porto = extrai_endereco(msg)
                # o próximo passo seria os dois roteadores se identificarem
                # um para o outro para que os vizinhos se reconheçam
                host = host.rstrip('\x00')
                try:
                    new_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    new_connection.connect((host, porto))

                    # enviamos nosso nome para o vizinho se identificar e aguardamos o nome dele para confirmar o handshake
                    new_connection.sendall(pack_router_name(my_name))
                    peer_router_name_bytes = recv_exactly(new_connection, 32)

                    if peer_router_name_bytes:
                        peer_router_name = unpack_router_name(peer_router_name_bytes)
                        with lock:
                            if peer_router_name in peer_router_name_to_socket:
                                # evitamos uma nova conexão com esse vizinho caso ela já existir
                                new_connection.close()
                            else:
                                peer_router_name_to_socket[peer_router_name] = new_connection
                                routing_table[peer_router_name] = (peer_router_name, 1)
                                sockets_list.append(new_connection)
                    else:
                        # o handshake falhou pois o vizinho não respondeu
                        new_connection.close()
                except Exception:
                    pass

            elif comando=='D':
                # o roteador recebe o NOME do outro roteador que deve ser removido
                # da sua lista de conexões
                msg=control.recv(32)
                roteador = extrai_roteador(msg)
                print(comando, roteador, flush=True)
                # OBS: o OUTRO roteador também deve remover a conexão de sua lista
                # há mais de uma forma de fazer isso, vocês devem determinar a sua

            elif comando=='E':
                # o roteador recebe o NOME do outro destino e o texto
                msg=control.recv(96)
                destino, texto = extrai_destino_texto(msg)
                print("%s %s '%s'" % (comando, destino, texto) ,flush=True)
                # a entrada com o destino na tabela de rotas identifica o próximo passo
                # a mensagem enviada deve ser repassada para um vizinho, se necessário

            elif comando=='T' or comando=='I':
                print(comando,flush=True)
                # cada comando vai exigir um tipo de reação do roteador que a recebe,
                # sua implementação deve decidir como tratar cada uma

            else:
                print("Comando não reconhecido",flush=True)
                # note que o programa a ser entregue não deve escrever nada além 
                # do que foi definido no enunciado; entretanto, na avaliação nenhum
                # roteador receberá comandos incorretos do programa de controle.
        
