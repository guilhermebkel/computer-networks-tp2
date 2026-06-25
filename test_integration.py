# Guilherme Mota, <Parceiro>
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

from struct import pack, unpack

WORK_DIR      = os.path.dirname(os.path.abspath(__file__))
TEST_INTERVAL = '0.2'   # anúncios rápidos nos testes (env RC_RIP_INTERVAL)
CONVERGE_WAIT = 2.0     # segundos aguardados para o DV convergir
INFINITY      = 16      # custo infinito conforme roteador.py


# ---------------------------------------------------------------------------
# Helpers de protocolo
# ---------------------------------------------------------------------------

def pack_name(name):
    return name.encode('ascii', errors='replace')[:32].ljust(32, b'\x00')


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# RouterProcess — gerencia um processo roteador.py como subprocesso
# ---------------------------------------------------------------------------

class RouterProcess:
    def __init__(self, port):
        self.port = port
        self._lines = []
        self._lock  = threading.Lock()
        env = os.environ.copy()
        env['RC_RIP_INTERVAL'] = TEST_INTERVAL
        self.proc = subprocess.Popen(
            ['python3', 'roteador.py', str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=WORK_DIR,
            env=env,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self):
        for raw in self.proc.stdout:
            with self._lock:
                self._lines.append(raw.decode().rstrip('\n'))

    def get_lines(self):
        with self._lock:
            return list(self._lines)

    def drain_lines(self):
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
            return lines

    def wait_for_lines(self, n, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self._lines) >= n:
                    return True
            time.sleep(0.05)
        return False

    def kill(self):
        self.proc.kill()
        self.proc.stdout.close()
        self.proc.wait()


# ---------------------------------------------------------------------------
# ControlConn — simula o programa de controle (controle.py)
# ---------------------------------------------------------------------------

class ControlConn:
    """
    Conecta via TCP ao roteador e envia apenas o nome na inicialização
    (sem address book), conforme o controle.py atualizado pelo professor.
    Armazena o dicionário de endereços para uso no comando connect().
    """

    def __init__(self, router_port, my_name, address_book,
                 retries=20, delay=0.15):
        self.address_book = address_book   # {name: (host, port)}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for _ in range(retries):
            try:
                self.sock.connect(('127.0.0.1', router_port))
                break
            except ConnectionRefusedError:
                time.sleep(delay)
        # Envia apenas o nome (32 bytes) — igual ao controle.py: pack("!32s", ...)
        self.sock.sendall(pack('!32s', my_name.encode()))

    def connect(self, name):
        """
        Envia comando 'C': pack("!c32sH", 'C', host, port) — igual ao controle.py.
        """
        host, port = self.address_book[name]
        msg = pack('!c32sH', b'C', host.encode(), port)
        self.sock.sendall(msg)

    def disconnect(self, name):
        """Envia comando 'D': pack("!c32s", 'D', name) — igual ao controle.py."""
        msg = pack('!c32s', b'D', name.encode())
        self.sock.sendall(msg)

    def table(self):
        self.sock.sendall(pack('!c', b'T'))

    def start(self):
        self.sock.sendall(pack('!c', b'I'))

    def send(self, dest, text):
        msg = pack('!c32s64s', b'E', dest.encode(), text.encode())
        self.sock.sendall(msg)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Função de setup de rede
# ---------------------------------------------------------------------------

def setup_network(names):
    """
    Cria RouterProcesses e ControlConns para os nomes fornecidos.
    Todos os roteadores recebem o mesmo address book (todos em 127.0.0.1).
    Retorna (routers_dict, ctrls_dict).
    """
    ports    = {name: find_free_port() for name in names}
    addr_book = {name: ('127.0.0.1', port) for name, port in ports.items()}

    routers = {name: RouterProcess(ports[name]) for name in names}
    ctrls   = {name: ControlConn(ports[name], name, addr_book) for name in names}

    return routers, ctrls


# ---------------------------------------------------------------------------
# Classe base com setUp/tearDown e helpers comuns
# ---------------------------------------------------------------------------

class BaseRouterTest(unittest.TestCase):

    def setUp(self):
        self.routers = {}
        self.ctrls   = {}

    def tearDown(self):
        for c in self.ctrls.values():
            c.close()
        for r in self.routers.values():
            r.kill()

    def start_all(self):
        for c in self.ctrls.values():
            c.start()

    def link(self, a, b):
        """
        Cria link A→B: só diz a A para conectar (igual ao controle.py que
        envia 'A roteador0 roteador1' apenas para roteador0). B aceita o inbound.
        """
        self.ctrls[a].connect(b)

    def unlink(self, a, b):
        """Remove link: diz a A para desconectar B; B detecta o fechamento TCP."""
        self.ctrls[a].disconnect(b)

    def wait_converge(self):
        time.sleep(CONVERGE_WAIT)

    def get_table(self, name):
        self.routers[name].drain_lines()
        self.ctrls[name].table()
        time.sleep(0.4)
        return self.routers[name].drain_lines()

    def parse_table(self, lines):
        """
        Converte 'T dest next_hop dist' em {dest: (dist, next_hop)}.
        Inclui rotas inacessíveis (dist=16) conforme exigido pelo enunciado.
        """
        result = {}
        for line in lines:
            parts = line.split()
            if len(parts) == 4 and parts[0] == 'T':
                try:
                    result[parts[1]] = (int(parts[3]), parts[2])
                except ValueError:
                    pass
        return result

    def assertReachable(self, dest, table, max_dist=INFINITY - 1):
        """Asserta que dest está acessível (dist < INFINITY) na tabela."""
        self.assertIn(dest, table, msg='%s ausente da tabela' % dest)
        dist, _ = table[dest]
        self.assertLess(dist, INFINITY,
                        msg='%s inacessível (dist=%d)' % (dest, dist))

    def assertUnreachable(self, dest, table):
        """
        Asserta que dest está inacessível: ausente da tabela ou dist >= INFINITY.
        Conforme enunciado, rotas com custo 16 permanecem na tabela.
        """
        if dest in table:
            dist, _ = table[dest]
            self.assertGreaterEqual(dist, INFINITY,
                msg='%s deveria ser inacessível mas dist=%d' % (dest, dist))


# ---------------------------------------------------------------------------
# TestRoteadorBasico — roteador isolado
# ---------------------------------------------------------------------------

class TestRoteadorBasico(BaseRouterTest):

    def setUp(self):
        super().setUp()
        self.routers, self.ctrls = setup_network(['A'])
        time.sleep(0.3)   # aguarda linhas de startup do esqueleto serem capturadas
        for r in self.routers.values():
            r.drain_lines()

    def test_tabela_inicial_contem_apenas_si_mesmo(self):
        """Sem vizinhos, T deve retornar somente a própria entrada com dist 0."""
        table = self.parse_table(self.get_table('A'))
        self.assertIn('A', table)
        self.assertEqual(table['A'], (0, 'A'))
        self.assertEqual(len(table), 1)

    def test_envio_para_si_mesmo(self):
        """E A texto deve imprimir 'R texto' pois o destino é o próprio roteador."""
        self.routers['A'].drain_lines()
        self.ctrls['A'].send('A', 'ola')
        time.sleep(0.3)
        self.assertIn('R ola', self.routers['A'].drain_lines())

    def test_start_nao_produz_saida(self):
        """Comando I não deve gerar nenhuma linha no stdout."""
        self.routers['A'].drain_lines()
        self.ctrls['A'].start()
        time.sleep(0.5)
        self.assertEqual(self.routers['A'].drain_lines(), [])

    def test_destino_desconhecido_descartado_silenciosamente(self):
        """E para destino sem rota não deve gerar saída nem exceção."""
        self.routers['A'].drain_lines()
        self.ctrls['A'].send('X', 'msg')
        time.sleep(0.3)
        self.assertEqual(self.routers['A'].drain_lines(), [])


# ---------------------------------------------------------------------------
# TestDoisRoteadores — topologia A–B
# ---------------------------------------------------------------------------

class TestDoisRoteadores(BaseRouterTest):

    def setUp(self):
        super().setUp()
        self.routers, self.ctrls = setup_network(['A', 'B'])
        self.start_all()
        self.link('A', 'B')
        self.wait_converge()

    def test_tabelas_mostram_vizinho_distancia_1(self):
        """Após A→B, ambas as tabelas devem conter o vizinho a distância 1."""
        tA = self.parse_table(self.get_table('A'))
        tB = self.parse_table(self.get_table('B'))
        self.assertEqual(tA.get('B'), (1, 'B'))
        self.assertEqual(tB.get('A'), (1, 'A'))

    def test_envio_direto_para_vizinho(self):
        """A envia E B ping → A imprime 'E B ping B', B imprime 'R ping'."""
        self.routers['A'].drain_lines()
        self.routers['B'].drain_lines()
        self.ctrls['A'].send('B', 'ping')
        time.sleep(0.5)
        self.assertIn('E B B ping', self.routers['A'].drain_lines())
        self.assertIn('R ping',     self.routers['B'].drain_lines())

    def test_desconexao_marca_rota_inacessivel(self):
        """Após D B em A, B deve aparecer inacessível (dist=16) na tabela de A."""
        self.ctrls['A'].disconnect('B')
        time.sleep(0.5)
        self.assertUnreachable('B', self.parse_table(self.get_table('A')))

    def test_desconexao_idempotente(self):
        """Dois D B seguidos não devem gerar erro nem saída espúria."""
        self.routers['A'].drain_lines()
        self.ctrls['A'].disconnect('B')
        self.ctrls['A'].disconnect('B')
        time.sleep(0.3)
        extra = [l for l in self.routers['A'].drain_lines()
                 if not l.startswith('T ')]
        self.assertEqual(extra, [])


# ---------------------------------------------------------------------------
# TestTresRoteadoresLinear — topologia A–B–C
# ---------------------------------------------------------------------------

class TestTresRoteadoresLinear(BaseRouterTest):

    def setUp(self):
        super().setUp()
        self.routers, self.ctrls = setup_network(['A', 'B', 'C'])
        self.start_all()
        self.link('A', 'B')
        self.link('B', 'C')
        self.wait_converge()

    def test_tabela_transitiva_em_a(self):
        """A deve ver C a distância 2 com next hop B."""
        tA = self.parse_table(self.get_table('A'))
        self.assertIn('C', tA)
        dist, nh = tA['C']
        self.assertEqual(dist, 2)
        self.assertEqual(nh, 'B')

    def test_tabela_completa_em_b(self):
        """B deve ver A e C a distância 1."""
        tB = self.parse_table(self.get_table('B'))
        self.assertEqual(tB.get('A'), (1, 'A'))
        self.assertEqual(tB.get('C'), (1, 'C'))

    def test_envio_transitivo(self):
        """A envia E C hello → A imprime 'E C hello B', B reencaminha, C recebe."""
        for r in self.routers.values():
            r.drain_lines()
        self.ctrls['A'].send('C', 'hello')
        time.sleep(0.5)
        self.assertIn('E C B hello', self.routers['A'].drain_lines())
        self.assertIn('E C C hello', self.routers['B'].drain_lines())
        self.assertIn('R hello',     self.routers['C'].drain_lines())

    def test_queda_link_bc_rota_para_c_inacessivel(self):
        """Após remover B–C, A e B devem ter C inacessível (dist=16)."""
        self.unlink('B', 'C')
        self.wait_converge()
        self.assertUnreachable('C', self.parse_table(self.get_table('A')))
        self.assertUnreachable('C', self.parse_table(self.get_table('B')))

    def test_queda_link_ab_rota_para_a_inacessivel_em_c(self):
        """Após remover A–B, C deve ter A inacessível (dist=16)."""
        self.unlink('A', 'B')
        self.wait_converge()
        self.assertUnreachable('A', self.parse_table(self.get_table('C')))


# ---------------------------------------------------------------------------
# TestConvergencia — surgimento e queda dinâmicos de links
# ---------------------------------------------------------------------------

class TestConvergencia(BaseRouterTest):

    def test_rota_aparece_apos_adicionar_link(self):
        """A ainda não vê C; após criar B–C a rota deve aparecer acessível."""
        self.routers, self.ctrls = setup_network(['A', 'B', 'C'])
        self.start_all()
        self.link('A', 'B')
        self.wait_converge()

        self.assertUnreachable('C', self.parse_table(self.get_table('A')))

        self.link('B', 'C')
        self.wait_converge()

        tA = self.parse_table(self.get_table('A'))
        self.assertIn('C', tA)
        self.assertEqual(tA['C'][0], 2)

    def test_reconexao_apos_queda_restaura_rota(self):
        """Rota que ficou inacessível após queda deve voltar com dist correta."""
        self.routers, self.ctrls = setup_network(['A', 'B', 'C'])
        self.start_all()
        self.link('A', 'B')
        self.link('B', 'C')
        self.wait_converge()

        self.assertReachable('C', self.parse_table(self.get_table('A')))

        self.unlink('B', 'C')
        self.wait_converge()
        self.assertUnreachable('C', self.parse_table(self.get_table('A')))

        self.link('B', 'C')
        self.wait_converge()
        tA = self.parse_table(self.get_table('A'))
        self.assertIn('C', tA)
        self.assertEqual(tA['C'][0], 2)

    def test_envio_antes_de_convergir_descartado(self):
        """Mensagem para destino sem rota ainda deve ser descartada sem erro."""
        self.routers, self.ctrls = setup_network(['A', 'B'])
        self.start_all()
        self.routers['A'].drain_lines()
        self.ctrls['A'].send('B', 'cedo')
        time.sleep(0.3)
        lines = self.routers['A'].drain_lines()
        self.assertFalse(any(l.startswith('E ') for l in lines))


# ---------------------------------------------------------------------------
# TestComControlePy — usa o controle.py real do professor como ponto de controle.
#
# O LEIA.ME avisa: "certifique-se de que seu programa roteador funciona
# corretamente com o programa de controle como fornecido, pois ele será o
# programa usado durante a avaliação."  Esses testes exercitam exatamente
# isso: disparam o controle.py via subprocess, alimentam comandos pela
# stdin e verificam a saída dos roteadores.
# ---------------------------------------------------------------------------

CONTROLE_PY = os.path.join(WORK_DIR, 'controle', 'controle.py')


class TestComControlePy(unittest.TestCase):

    def setUp(self):
        self._procs = []
        self._tmp   = []

    def tearDown(self):
        for p in self._procs:
            try:
                p.kill()
                p.stdout.close()
                p.wait()
            except Exception:
                pass
        for f in self._tmp:
            try:
                os.unlink(f)
            except Exception:
                pass

    # --- helpers ---

    def _start_routers(self, names):
        """Inicia roteadores e devolve (ports, output_buffers)."""
        ports = {n: find_free_port() for n in names}
        bufs  = {}
        env   = os.environ.copy()
        env['RC_RIP_INTERVAL'] = TEST_INTERVAL

        for name in names:
            p = subprocess.Popen(
                ['python3', 'roteador.py', str(ports[name])],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=WORK_DIR,
                env=env,
            )
            self._procs.append(p)
            lines, lk = [], threading.Lock()
            bufs[name] = (lines, lk)

            def _read(proc=p, lst=lines, lock=lk):
                for raw in proc.stdout:
                    with lock:
                        lst.append(raw.decode().rstrip('\n'))

            threading.Thread(target=_read, daemon=True).start()

        time.sleep(0.4)   # aguarda roteadores ficarem prontos para aceitar
        return ports, bufs

    def _run_controle(self, ports, names, commands):
        """Cria roteadores.txt temporário e executa controle.py até EOF."""
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
            for n in names:
                f.write('%s localhost %d\n' % (n, ports[n]))
            fname = f.name
        self._tmp.append(fname)

        subprocess.run(
            ['python3', CONTROLE_PY, fname],
            input=commands, text=True,
            capture_output=True,
            cwd=WORK_DIR,
            timeout=20,
        )

    def _lines(self, bufs, name):
        lines, lk = bufs[name]
        with lk:
            return list(lines)

    def _parse_table(self, lines):
        result = {}
        for line in lines:
            parts = line.split()
            if len(parts) == 4 and parts[0] == 'T':
                try:
                    result[parts[1]] = (int(parts[3]), parts[2])
                except ValueError:
                    pass
        return result

    # --- testes ---

    def test_dois_roteadores_com_controle_py(self):
        """
        controle.py: I; A A B; P 1; T A; E A B hello
        Verifica tabela de A e recebimento em B.
        """
        names = ['A', 'B']
        ports, bufs = self._start_routers(names)

        # 'A A B' → controle envia 'C localhost port_B' apenas para A;
        # B aceita o inbound. P 1 = 1 s real para convergência.
        self._run_controle(ports, names, 'I\nA A B\nP 1\nT A\nE A B hello\n')
        time.sleep(0.4)

        table_A = self._parse_table(self._lines(bufs, 'A'))
        self.assertIn('B', table_A)
        self.assertEqual(table_A['B'][0], 1)                 # dist=1

        out_A = self._lines(bufs, 'A')
        out_B = self._lines(bufs, 'B')
        self.assertTrue(any('E B B hello' in l for l in out_A),
                        msg='A deveria imprimir "E B B hello"')
        self.assertIn('R hello', out_B)

    def test_tres_roteadores_transitivo_com_controle_py(self):
        """
        controle.py: I; A A B; A B C; P 2; T A; E A C ola
        Verifica roteamento transitivo A→B→C com controle.py real.
        """
        names = ['A', 'B', 'C']
        ports, bufs = self._start_routers(names)

        self._run_controle(ports, names,
                           'I\nA A B\nA B C\nP 2\nT A\nE A C ola\n')
        time.sleep(0.4)

        table_A = self._parse_table(self._lines(bufs, 'A'))
        self.assertIn('C', table_A)
        self.assertEqual(table_A['C'][0], 2)                 # dist=2
        self.assertEqual(table_A['C'][1], 'B')               # via B

        out_A = self._lines(bufs, 'A')
        out_B = self._lines(bufs, 'B')
        out_C = self._lines(bufs, 'C')
        self.assertTrue(any('E C B ola' in l for l in out_A),
                        msg='A deveria imprimir "E C B ola"')
        self.assertTrue(any('E C C ola' in l for l in out_B),
                        msg='B deveria imprimir "E C C ola"')
        self.assertIn('R ola', out_C)

    def test_queda_de_link_com_controle_py(self):
        """
        controle.py: I; A A B; A B C; P 2; R B C; P 2; T A
        Verifica que após remover B–C, C fica inacessível em A (dist=16).
        """
        names = ['A', 'B', 'C']
        ports, bufs = self._start_routers(names)

        # 'R B C' → controle envia 'D C' para B; C detecta TCP close.
        self._run_controle(ports, names,
                           'I\nA A B\nA B C\nP 2\nR B C\nP 2\nT A\n')
        time.sleep(0.4)

        table_A = self._parse_table(self._lines(bufs, 'A'))
        if 'C' in table_A:
            dist_C = table_A['C'][0]
            self.assertGreaterEqual(dist_C, INFINITY,
                msg='C deveria ser inacessível (dist=16) em A, mas dist=%d' % dist_C)


# ---------------------------------------------------------------------------
# TestComMaquinasDCC — roteador local conectado a máquinas reais do DCC
#
# Pré-requisito: iniciar os roteadores remotos ANTES de rodar os testes.
#
# Uso:
#   RC_RIP_DCC_ROUTERS="vulcan:150.164.4.47:11111" make test
#   RC_RIP_DCC_ROUTERS="vulcan:150.164.4.47:11111,risa:cristal.dcc.ufmg.br:4321" make test-dcc
#
# Formato da variável: "nome:host:porta" separados por vírgula.
# Os roteadores DCC devem estar rodando antes de executar esses testes.
# ---------------------------------------------------------------------------

def _parse_dcc_routers():
    raw = os.environ.get('RC_RIP_DCC_ROUTERS', '')
    result = {}
    for entry in raw.split(','):
        entry = entry.strip()
        if not entry:
            continue
        # separa pelo último ':' (porta) e pelo penúltimo (host), para
        # não quebrar em hostnames simples como cristal.dcc.ufmg.br:4321
        parts = entry.split(':')
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        host = ':'.join(parts[1:-1]).strip()  # suporta IPv6 no meio
        try:
            port = int(parts[-1].strip())
            result[name] = (host, port)
        except ValueError:
            pass
    return result

_DCC_ROUTERS = _parse_dcc_routers()


@unittest.skipUnless(_DCC_ROUTERS, 'RC_RIP_DCC_ROUTERS não configurado — esses testes só rodam contra máquinas do DCC')
class TestComMaquinasDCC(BaseRouterTest):
    """
    Sobe um roteador local e o conecta ao(s) roteador(es) já rodando no DCC,
    verificando convergência e encaminhamento entre máquinas reais.

    Exemplos de uso:
      RC_RIP_DCC_ROUTERS="grande:grande.grad.dcc.ufmg.br:11111" make test
      RC_RIP_DCC_ROUTERS="grande:grande.grad.dcc.ufmg.br:11111,outra:outra.dcc.ufmg.br:22222" make test-dcc
    """

    def setUp(self):
        super().setUp()
        self.dcc_routers    = _DCC_ROUTERS
        self._dcc_ctrl_socks = []

        # O roteador.py bloqueia em server_socket.accept() esperando o controle.py
        # conectar antes de entrar no while loop. O teste assume esse papel: conecta
        # a cada roteador DCC e envia seu nome, desbloqueando-o para aceitar vizinhos.
        for dcc_name, (dcc_host, dcc_port) in self.dcc_routers.items():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect((dcc_host, dcc_port))
                s.sendall(pack('!32s', dcc_name.encode()))
                s.settimeout(None)
                self._dcc_ctrl_socks.append(s)
            except Exception as e:
                self.skipTest(
                    'Não foi possível conectar ao roteador DCC %s (%s:%d): %s'
                    % (dcc_name, dcc_host, dcc_port, e)
                )

        local_port = find_free_port()
        addr_book  = {'local': ('127.0.0.1', local_port)}
        addr_book.update({n: (h, p) for n, (h, p) in self.dcc_routers.items()})

        self.routers['local'] = RouterProcess(local_port)
        self.ctrls['local']   = ControlConn(local_port, 'local', addr_book)

    def tearDown(self):
        super().tearDown()
        for s in self._dcc_ctrl_socks:
            try:
                s.close()
            except Exception:
                pass

    def _first_dcc(self):
        return next(iter(self.dcc_routers))

    def test_tabela_apos_conectar_a_dcc(self):
        """Tabela local deve mostrar o roteador DCC a distância 1 após convergência."""
        dcc = self._first_dcc()
        self.ctrls['local'].start()
        self.ctrls['local'].connect(dcc)
        self.wait_converge()

        table = self.parse_table(self.get_table('local'))
        self.assertIn(dcc, table,
                      msg='Roteador DCC "%s" não aparece na tabela local' % dcc)
        dist, _ = table[dcc]
        self.assertEqual(dist, 1,
                         msg='Distância para "%s" deveria ser 1, mas é %d' % (dcc, dist))

    def test_envio_para_roteador_dcc(self):
        """Local envia E → deve imprimir 'E <dcc> <dcc> texto' antes de encaminhar."""
        dcc = self._first_dcc()
        self.ctrls['local'].start()
        self.ctrls['local'].connect(dcc)
        self.wait_converge()

        self.routers['local'].drain_lines()
        self.ctrls['local'].send(dcc, 'teste_dcc')
        time.sleep(1.0)

        lines    = self.routers['local'].drain_lines()
        expected = 'E %s %s teste_dcc' % (dcc, dcc)
        self.assertTrue(any(expected in l for l in lines),
                        msg='Esperava "%s" nas linhas: %s' % (expected, lines))

    def test_rota_inacessivel_apos_desconectar_dcc(self):
        """Após D, o roteador DCC deve aparecer inacessível (dist=16) na tabela local."""
        dcc = self._first_dcc()
        self.ctrls['local'].start()
        self.ctrls['local'].connect(dcc)
        self.wait_converge()

        self.ctrls['local'].disconnect(dcc)
        self.wait_converge()

        table = self.parse_table(self.get_table('local'))
        self.assertUnreachable(dcc, table)

    def test_rotas_transitivas_via_dcc(self):
        """
        Com 2+ roteadores DCC conectados entre si, o local deve aprender rotas
        transitivas através do primeiro. Requer os DCC já linkados entre si.
        """
        if len(self.dcc_routers) < 2:
            self.skipTest('Requer 2+ roteadores DCC em RC_RIP_DCC_ROUTERS')

        names     = list(self.dcc_routers.keys())
        dcc_first  = names[0]
        dcc_second = names[1]

        self.ctrls['local'].start()
        self.ctrls['local'].connect(dcc_first)
        self.wait_converge()

        table = self.parse_table(self.get_table('local'))
        self.assertIn(dcc_second, table,
                      msg='Rota transitiva para "%s" não apareceu na tabela local' % dcc_second)
        dist, nh = table[dcc_second]
        self.assertLess(dist, INFINITY,
                        msg='"%s" inacessível (dist=%d)' % (dcc_second, dist))
        self.assertEqual(nh, dcc_first,
                         msg='Next hop para "%s" deveria ser "%s", mas é "%s"' % (
                             dcc_second, dcc_first, nh))


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    unittest.main(verbosity=2)
