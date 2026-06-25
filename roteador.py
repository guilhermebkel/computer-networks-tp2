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
my_name = l[0].decode().rstrip('\x00') # removemos o padding de nulos para que comparações simples funcionem corretamente
print(my_name,flush=True)


####################################################################
# a partir deste ponto, certamente seu programa precisará ser alterado
# para incluir o uso do select para observar as conexões existentes e
# novas que surjam de outros roteadores, bem como enviar periodicamente
# as mensagens do protocolo de roteamento para os seus vizinhos imediados
####################################################################

import os
import select
import threading

lock = threading.Lock()
sockets_list = []
routing_table = {}
peer_router_name_to_peer_socket = {}
timer = None

INFINITY = 16 # valor do custo infinito conforme o RIP
ROUTE_MESSAGE_TYPE = ord('R')  # mensagem de anúncio de vetor de distâncias
FORWARD_MESSAGE_TYPE = ord('F') # mensagem de encaminhamento de mensagem de dados
ANNOUNCE_INTERVAL = float(os.environ.get('RC_RIP_INTERVAL', '1.0')) # intervalo entre anúncios DV, alterável via variável de ambiente


# o roteador sempre se conhece com distancia zero
routing_table[my_name] = (my_name, 0)
sockets_list = [server_socket, control]

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

# seguindo a lógica do RIP, ao perder um vizinho, todas as rotas que passavam por ele recebem custo infinito para sinalizar que estão inacessíveis
def remove_peer_routes(name):
    with lock:
        for destination in list(routing_table):
            route_via, _ = routing_table[destination]
            if route_via == name and destination != my_name:
                routing_table[destination] = (name, INFINITY)

        if name in routing_table:
            routing_table[name] = (name, INFINITY)

def pack_forward_router_message(dest, text):
    text_in_bytes = text.encode('ascii', errors='replace')[:64].ljust(64, b'\x00')
    return bytes([FORWARD_MESSAGE_TYPE]) + pack_router_name(dest) + text_in_bytes

def pack_route_update_message(exclude_next_hop=None):
    with lock:
        entries = []
        for dest, (nh, dist) in routing_table.items():
            # aqui usamos 'split horizon' para anunciar custo infinito para rotas cujo próximo salto é o próprio destinatário, evitando loops
            entries.append((dest, INFINITY if nh == exclude_next_hop else dist))

    parts = [bytes([ROUTE_MESSAGE_TYPE]), pack_router_name(my_name), pack('!H', len(entries))]
    for dest, dist in entries:
        parts.append(pack_router_name(dest) + pack('!H', dist))
    return b''.join(parts)


def announce_route_updates_now():
    with lock:
        peer_items = list(peer_router_name_to_peer_socket.items())
    for peer_name, peer_socket in peer_items:
        try:
            peer_socket.sendall(pack_route_update_message(exclude_next_hop=peer_name))
        except Exception:
            pass


def announce_route_updates():
    global timer
    announce_route_updates_now()
    # reagenda pro próprio roteador para manter o anúncio periódico contínuo
    timer = threading.Timer(ANNOUNCE_INTERVAL, announce_route_updates)
    timer.daemon = True
    timer.start()

def update_distance_vector(sender, routes):
    route_set = {destino for destino, _ in routes}
    with lock:
        for d in list(routing_table):
            if routing_table[d][0] == sender and d not in route_set and d != my_name:
                routing_table[d] = (sender, INFINITY)
        for destino, dist in routes:
            if destino == my_name:
                continue
            new_distance = min(dist + 1, INFINITY)
            if destino not in routing_table:
                routing_table[destino] = (sender, new_distance)
            elif routing_table[destino][0] == sender:
                routing_table[destino] = (sender, new_distance)
            elif routing_table[destino][1] > new_distance:
                routing_table[destino] = (sender, new_distance)

while(True):  # aguarda mensagens do comando de controle
    try:
        readable, _, _ = select.select(sockets_list, [], [])
    except (ValueError, OSError):
        break

    for socket_item in list(readable):
        # novas conexões de roteadores vizinhos
        if socket_item is server_socket:
            connection, _ = server_socket.accept()
            peer_router_name_in_bytes = recv_exactly(connection, 32)

            if not peer_router_name_in_bytes:
                connection.close()
                continue

            peer_router_name = unpack_router_name(peer_router_name_in_bytes)

            # enviamos o nome do nosso roteador de volta
            connection.sendall(pack_router_name(my_name))

            with lock:
                if peer_router_name in peer_router_name_to_peer_socket:
                    # evitamos uma nova conexão com esse vizinho caso ela já existir
                    connection.close()
                else:
                    peer_router_name_to_peer_socket[peer_router_name] = connection
                    routing_table[peer_router_name] = (peer_router_name, 1)
                    sockets_list.append(connection)

        # mensagens do programa de controle
        elif socket_item is control:
            msg = control.recv(1)   # no roteador, não haverá apenas essa conexão
            if not msg or msg=='':
                print("Connection closed",flush=True)
                sys.exit()
            c = unpack("!c",msg)
            comando = c[0].decode()

            if comando=='C':
                # o roteador recebe o ENDEREÇO do outro roteador ao qual se conectar
                msg=recv_exactly(control, 34)
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
                            if peer_router_name in peer_router_name_to_peer_socket:
                                # evitamos uma nova conexão com esse vizinho caso ela já existir
                                new_connection.close()
                            else:
                                peer_router_name_to_peer_socket[peer_router_name] = new_connection
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
                msg=recv_exactly(control, 32)
                roteador = extrai_roteador(msg).rstrip('\x00')
                # OBS: o OUTRO roteador também deve remover a conexão de sua lista
                # há mais de uma forma de fazer isso, vocês devem determinar a sua

                with lock:
                    peer_socket = peer_router_name_to_peer_socket.pop(roteador, None)

                if peer_socket:
                    if peer_socket in sockets_list:
                        sockets_list.remove(peer_socket)
                    try:
                        peer_socket.close()
                    except Exception:
                        pass
                    remove_peer_routes(roteador)
                    announce_route_updates_now()

            elif comando=='E':
                # o roteador recebe o NOME do outro destino e o texto
                msg=recv_exactly(control, 96)
                destino, texto = extrai_destino_texto(msg)
                # a entrada com o destino na tabela de rotas identifica o próximo passo
                # a mensagem enviada deve ser repassada para um vizinho, se necessário

                destino = destino.rstrip('\x00')
                texto = texto.rstrip('\x00')

                # a mensagem chegou ao destino final
                if destino == my_name:
                    print('R %s' % texto, flush=True)
                else:
                    with lock:
                        route = routing_table.get(destino)

                    # só encaminha se há rota conhecida e o destino está acessível
                    if route and route[1] < INFINITY:
                        next_hop, _ = route
                        print('E %s %s %s' % (destino, next_hop, texto), flush=True)

                        with lock:
                            next_hop_peer_socket = peer_router_name_to_peer_socket.get(next_hop)

                        if next_hop_peer_socket:
                            try:
                                next_hop_peer_socket.sendall(pack_forward_router_message(destino, texto))
                            except Exception:
                                pass

            elif comando=='T' or comando=='I':
                # cada comando vai exigir um tipo de reação do roteador que a recebe,
                # sua implementação deve decidir como tratar cada uma

                # caso o comando for 'T', imprime a tabela de roteamento atual
                if comando=='T':
                    with lock:
                        rows = list(routing_table.items())
                    for dest, (next_hop, dist) in rows:
                        print('T %s %s %d' % (dest, next_hop, dist), flush=True)
                # caso o comando for 'I', inicia o temporizador de anúncio periódico de rotas
                else:
                    if timer is None:
                        timer = threading.Timer(ANNOUNCE_INTERVAL, announce_route_updates)
                        timer.daemon = True
                        timer.start()

            else:
                # note que o programa a ser entregue não deve escrever nada além 
                # do que foi definido no enunciado; entretanto, na avaliação nenhum
                # roteador receberá comandos incorretos do programa de controle.
                pass

        # mensagens de roteadores vizinhos
        else:
            type_in_bytes = recv_exactly(socket_item, 1)
            # conexão fechada pelo par
            if not type_in_bytes:
                # remove o par das estruturas internas
                roteador = None
                with lock:
                    for name, s in list(peer_router_name_to_peer_socket.items()):
                        if s is socket_item:
                            roteador = name
                            break
                if roteador:
                    with lock:
                        peer_router_name_to_peer_socket.pop(roteador, None)
                    if socket_item in sockets_list:
                        sockets_list.remove(socket_item)
                    try:
                        socket_item.close()
                    except Exception:
                        pass
                    remove_peer_routes(roteador)
                else:
                    if socket_item in sockets_list:
                        sockets_list.remove(socket_item)
                    try:
                        socket_item.close()
                    except Exception:
                        pass
                continue

            type_byte = type_in_bytes[0]

            # mensagem de anúncio de vetor de distâncias (R)
            if type_byte == ROUTE_MESSAGE_TYPE:
                header = recv_exactly(socket_item, 34)  # 32 bytes nome do remetente + 2 bytes número de entradas
                if not header:
                    continue
                sender = unpack_router_name(header[:32])
                num_entries = unpack('!H', header[32:34])[0]

                routes = []
                for _ in range(num_entries):
                    entry = recv_exactly(socket_item, 34)
                    if not entry:
                        break
                    destino = unpack_router_name(entry[:32])
                    dist = unpack('!H', entry[32:])[0]
                    routes.append((destino, dist))
                update_distance_vector(sender, routes)

            # mensagem de encaminhamento de dados (F)
            elif type_byte == FORWARD_MESSAGE_TYPE:
                msg = recv_exactly(socket_item, 96)  # 32 bytes destino + 64 bytes texto
                if not msg:
                    continue
                destino, texto = extrai_destino_texto(msg)
                destino = destino.rstrip('\x00')
                texto = texto.rstrip('\x00')

                # chegou ao destino final
                if destino == my_name:
                    print('R %s' % texto, flush=True)
                else:
                    with lock:
                        route = routing_table.get(destino)

                    if route and route[1] < INFINITY:
                        next_hop, _ = route
                        print('E %s %s %s' % (destino, next_hop, texto), flush=True)

                        with lock:
                            next_hop_peer_socket = peer_router_name_to_peer_socket.get(next_hop)

                        if next_hop_peer_socket:
                            try:
                                next_hop_peer_socket.sendall(pack_forward_router_message(destino, texto))
                            except Exception:
                                pass
            else:
                # tipo desconhecido: ignora
                continue
