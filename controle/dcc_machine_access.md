# Acesso às máquinas do DCC

## 1. Entrar no gateway
```sh
ssh seu_login@login.dcc.ufmg.br
```

## 2. De lá, acessar uma máquina do lab
```sh
ssh grande.grad.dcc.ufmg.br
```

A lista completa de máquinas disponíveis está em:
https://www.crc.dcc.ufmg.br/infraestrutura/laboratorios/linux

## 3. Clonar repositório do Github:
```sh
git clone https://github.com/guilhermebkel/computer-networks-tp2
```

## 4. Instalar dependências:
```sh
pip3 install pytest --user
```

## 4. Testar código

### Local

```sh
make test
```

### Produção

Máquina A (produção - dcc):
```sh
make run port=5555
```

Máquina B (produção - dcc):
```sh
make run port=4444
```

Máquina C (produção - dcc):
```sh
RC_RIP_DCC_ROUTERS="grande:grande.grad.dcc.ufmg.br:5555,grande:grande.grad.dcc.ufmg.br:4444" make test
```
