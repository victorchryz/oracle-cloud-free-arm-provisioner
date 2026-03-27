# Oracle Cloud Free Tier ARM Provisioner

Ferramenta Docker para provisionar instâncias ARM Free Tier da Oracle Cloud (4 OCPU, 24GB RAM) com lógica de retry automática e notificações via Telegram.

## O que é o Oracle Cloud Free Tier?

A Oracle oferece uma camada gratuita permanente que inclui:

- **ARM (A1)**: Até 4 OCPU e 24GB RAM - **este projeto provisiona automaticamente**
- **Micro (E2)**: 1 OCPU e 1GB RAM - sempre disponível

O problema é que as instâncias ARM são muito disputadas e frequentemente retornam "Out of Capacity". Este script automatiza as tentativas até conseguir.

## Como funciona

1. Tenta criar a instância em cada Availability Domain (AD-1, AD-2, AD-3)
2. Se der "Out of Capacity", espera 20 segundos e tenta o próximo AD
3. Após tentar todos os ADs, espera 60 segundos e reinicia o ciclo
4. Quando consegue criar, notifica via Telegram e para automaticamente

## Pré-requisitos

- Docker
- Conta Oracle Cloud (Free Tier)
- Credenciais OCI API
- Bot do Telegram (opcional, para notificações)

## Instalação no Fedora Aurora/Kinoite

```bash
rpm-ostree install docker docker-compose
sudo reboot
```

## Configuração

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/oracle-cloud-free-arm-provisioner.git
cd oracle-cloud-free-arm-provisioner
```

### 2. Criar `oci.env`

```bash
cp oci.env.example oci.env
```

Edite o `oci.env` com suas preferências:

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `OCT_FREE_AD` | Availability Domains a tentar | `AD-1,AD-2,AD-3` |
| `DISPLAY_NAME` | Nome da instância | `minha-vps-arm` |
| `OCI_COMPUTE_SHAPE` | Tipo de instância | `VM.Standard.A1.Flex` |
| `AD_WAIT_TIME_SECS` | Espera entre ADs | `20` |
| `REQUEST_WAIT_TIME_SECS` | Espera entre ciclos | `60` |
| `OPERATING_SYSTEM` | Sistema operacional | `Canonical Ubuntu` |
| `OS_VERSION` | Versão do SO | `24.04 Minimal aarch64` |
| `BOOT_VOLUME_SIZE` | Tamanho do disco (GB) | `200` |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram | (opcional) |
| `TELEGRAM_CHAT_ID` | Chat ID Telegram | (opcional) |

### 3. Criar `oci_config`

1. Acesse o [Console Oracle Cloud](https://cloud.oracle.com)
2. Clique no seu perfil → **My Profile** → **API Keys** → **Add API Key**
3. Baixe a chave privada (arquivo `.pem`)
4. Copie as informações mostradas

```bash
cp oci_config.example oci_config
```

Edite o `oci_config`:

```ini
[DEFAULT]
user=ocid1.user.oc1..seu_user_ocid
fingerprint=xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx:xx
tenancy=ocid1.tenancy.oc1..seu_tenancy_ocid
region=us-ashburn-1
key_file=/app/oci_api_private_key.pem
```

### 4. Adicionar chave privada API

Renomeie o arquivo `.pem` baixado do console:

```bash
mv ~/Downloads/sua-chave.pem oci_api_private_key.pem
```

### 5. Criar chave SSH para acessar a VPS

```bash
ssh-keygen -t ed25519 -C "seu@email.com" -f ~/.ssh/oracle_vps
cp ~/.ssh/oracle_vps.pub ssh_public_key.pub
```

### 6. Configurar Telegram (opcional)

1. No Telegram, procure por **@BotFather**
2. Envie `/newbot` e siga as instruções
3. Copie o token gerado
4. Mande uma mensagem para o seu bot
5. Acesse: `https://api.telegram.org/bot<TOKEN>/getUpdates`
6. Copie o `chat.id` do JSON

Adicione ao `oci.env`:

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

## Executar

```bash
docker-compose up -d
docker-compose logs -f
```

O container vai ficar tentando até conseguir criar a instância. Você receberá uma notificação no Telegram quando:

- Script iniciar
- Cada erro de "Out of Capacity"
- Instância criada com sucesso

Quando a instância for criada, o container para automaticamente.

## Parar o container

```bash
docker-compose down
```

## Estrutura de arquivos

```
oracle-cloud-free-arm-provisioner/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── oci.env.example          # Template de configuração
├── oci_config.example       # Template de credenciais
├── oci.env                  # Suas configurações (NÃO commitar)
├── oci_config               # Suas credenciais (NÃO commitar)
├── oci_api_private_key.pem  # Sua chave API (NÃO commitar)
├── ssh_public_key.pub       # Sua chave SSH (NÃO commitar)
├── src/
│   └── main.py
└── README.md
```

## Região da conta

**Importante:** A região é definida na criação da conta Oracle Cloud. Você não pode criar instâncias Free Tier em outras regiões além da sua "home region". Se sua conta foi criada em `us-ashburn-1`, você só pode criar instâncias Free Tier lá.

## Testar com instância Micro

Para testar se a automação está funcionando, você pode tentar criar uma instância Micro (sempre disponível):

No `oci.env`:

```bash
OCI_COMPUTE_SHAPE=VM.Standard.E2.1.Micro
OS_VERSION=24.04 Minimal
```

Quando confirmar que funciona, volte para ARM:

```bash
OCI_COMPUTE_SHAPE=VM.Standard.A1.Flex
OS_VERSION=24.04 Minimal aarch64
```

## Troubleshooting

### "ConfigFileNotFound"

Verifique se `oci_config` está correto e o caminho `key_file` aponta para `/app/oci_api_private_key.pem`.

### "NotAuthorizedOrNotFound"

As credenciais podem estar incorretas. Verifique `user`, `tenancy` e `fingerprint`.

### "Out of host capacity"

Normal! A região está sem capacidade de ARM. O script continua tentando.

### Container reinicia em loop

Verifique se está usando `restart: on-failure` no `docker-compose.yml`.

## Referências

- [mohankumarpaluru/oracle-freetier-instance-creation](https://github.com/mohankumarpaluru/oracle-freetier-instance-creation)
- [Nyamort/oracle-freetier-instance-creation](https://github.com/Nyamort/oracle-freetier-instance-creation)

## Licença

MIT
