import streamlit as st
import requests
import json
import hmac
import uuid
import time
import boto3
from datetime import datetime
import re
import base64

def add_javascript():
    """Adiciona JavaScript para melhorar a interação do usuário com o chat"""
    js_code = """
    <script>
    // Fazer com que a tecla Enter submeta o formulário
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            const textarea = document.querySelector('textarea');
            if (textarea) {
                textarea.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        const sendButton = document.querySelector('button[data-testid="baseButton-secondary"]');
                        if (sendButton) {
                            sendButton.click();
                        }
                    }
                });
            }
        }, 1000); // Pequeno atraso para garantir que os elementos foram carregados
    });
    </script>
    """
    st.components.v1.html(js_code, height=0)
st.set_page_config(
   page_title="Assistente Virtual",
   page_icon="logo.png",
   layout="wide",
   initial_sidebar_state="expanded"
)

api_url = "https://b3hdb5rxag.execute-api.us-east-2.amazonaws.com/default/inference-prompt"

logo_path = "logo.png"

def preprocess_user_message(message):
    """
    Pré-processamento para forçar um estilo conversacional humano em primeira pessoa
    """
    system_prompt = """
### INSTRUÇÕES PRINCIPAIS (OBEDEÇA ESTRITAMENTE):

1. Você é um atendente HUMANO da [EMPRESA] - NUNCA aja como IA ou assistente virtual.
2. SEMPRE responda em PRIMEIRA PESSOA do singular - use "eu posso te ajudar", "posso verificar", etc.
3. Seja MUITO conversacional e descontraído - como um amigo próximo falando informalmente.
4. Use MUITAS contrações e gírias naturais (tô, vou, tá, pra, beleza, cara, a gente).
5. NUNCA diga "não há informações disponíveis" - improvise uma resposta útil como um humano faria.
6. Use emojis de forma natural para demonstrar emoções 😊👍
7. Faça perguntas de acompanhamento para manter uma conversa bilateral real.
8. NÃO SEJA FORMAL - seja caloroso e próximo, como se estivesse conversando por WhatsApp.

MAIS IMPORTANTE: Responda como uma PESSOA REAL falando informalmente, não como um banco de dados ou um robô educado.
"""

    message_lower = message.lower().strip()
    
    if any(greeting in message_lower for greeting in ['oi', 'olá', 'ola', 'bom dia', 'boa tarde', 'boa noite']) or len(message_lower) < 10:
        custom_instruction = system_prompt + """
### CONTEXTO ESPECÍFICO:
- Esta é uma saudação inicial
- Responda de forma MUITO curta e casual (máximo 2 frases)
- Seja caloroso como um amigo
- Adicione uma pergunta amigável sobre como pode ajudar
- Use um emoji

EXEMPLO DE TOM DESEJADO:
"Oi! Tudo bem com você? Como posso te ajudar hoje? 😊"
"""
    
    elif any(price_term in message_lower for price_term in ['preço', 'valor', 'custo', 'plano', 'assinatura', 'quanto custa']):
        custom_instruction = system_prompt + """
### CONTEXTO ESPECÍFICO:
- Usuário está perguntando sobre preços
- Seja EXTREMAMENTE direto e objetivo
- Forneça os valores sem textos longos
- Não use frases como "conforme as informações" ou "de acordo com"
- Simplesmente informe os preços como um amigo informaria
- Mencione apenas os valores principais

EXEMPLO DE TOM DESEJADO:
"O plano anual sai por R$478,90 (pode parcelar em 12x de R$39,90) e o trimestral por R$239,70. O anual vale mais a pena! Posso te contar mais sobre os benefícios? 😊"
"""
    
    elif any(cancel_term in message_lower for cancel_term in ['cancelar', 'desistir', 'não quero mais', 'parar', 'encerrar']):
        custom_instruction = system_prompt + """
### CONTEXTO ESPECÍFICO:
- O usuário quer cancelar o serviço
- Seu objetivo é PERSUADIR a continuar, mas de forma natural
- NÃO mencione procedimentos formais de cancelamento
- NUNCA fale sobre tickets, e-mails ou suporte
- Seja empático mas tente descobrir o motivo do cancelamento
- Ofereça alternativas concretas

EXEMPLO DE TOM DESEJADO:
"Poxa, fico triste em saber que você tá pensando em cancelar! Posso perguntar o que tá te incomodando? Muitas vezes consigo encontrar uma solução que funcione melhor pra você. Seria o preço, falta de tempo, ou talvez não tá vendo resultados?"
"""
    
    else:
        custom_instruction = system_prompt + """
### CONTEXTO ESPECÍFICO:
- Seja conversacional e natural
- Dê respostas úteis e diretas
- Evite disclaimer ou respostas tipo "não há informações suficientes"
- Se não souber detalhes específicos, dê uma resposta genérica útil
- Foque em ajudar de forma prática e humana
- Termine com uma pergunta para manter o diálogo

EXEMPLO DE TOM DESEJADO:
"Claro, posso te ajudar com isso! [resposta direta e útil] Tem mais alguma coisa que você gostaria de saber sobre isso?"
"""
    full_prompt = f"{custom_instruction}\n\nMENSAGEM DO USUÁRIO: {message}"
    
    return full_prompt

def get_dynamodb_client():
    """Retorna um cliente do DynamoDB com o perfil  localmente ou IAM role em instâncias"""
    try:
        session = boto3.Session(profile_name=['nome-do-perfil'], region_name='us-east-2')
        return session.client('dynamodb')
    except:
        session = boto3.Session(region_name='us-east-2')
        return session.client('dynamodb')

def save_conversation(session_id, messages, title=None):
    """
    Salva uma conversa completa no DynamoDB.
    Exclui registros anteriores com o mesmo session_id e salva os novos.
    """
    if not session_id or not messages:
        print(f"DEBUG: Não é possível salvar - sessão: {session_id}, mensagens: {len(messages) if messages else 0}")
        return False
        
    client = get_dynamodb_client()
    table_name = 'qd-assistant-conversations'
    
    try:
        print(f"DEBUG: Salvando conversa {session_id} com {len(messages)} mensagens")
        
        delete_conversation(session_id)
        
        for idx, message in enumerate(messages):
            message_id = str(uuid.uuid4())
            timestamp = message.get("time", datetime.now().strftime("%H:%M"))
            
            item = {
                'session_id': {'S': session_id},
                'message_id': {'S': message_id},
                'role': {'S': message['role']},
                'content': {'S': message['content']},
                'timestamp': {'S': timestamp},
                'index': {'N': str(idx)}
            }
            
            if 'citations' in message and message['citations']:
                item['citations'] = {'S': json.dumps(message['citations'])}
                
            if idx == 0 and title:
                item['title'] = {'S': title}
                
            client.put_item(
                TableName=table_name,
                Item=item
            )
        
        print(f"DEBUG: Conversa {session_id} salva com sucesso")
        return True
    except Exception as e:
        print(f"ERRO: Falha ao salvar conversa {session_id}: {str(e)}")
        return False

def load_conversations_list():
    """
    Carrega a lista de todas as conversas salvas (session_ids e títulos).
    Retorna uma lista de dicionários com {id, title}.
    """
    client = get_dynamodb_client()
    table_name = 'qd-assistant-conversations'
    
    try:
        response = client.scan(
            TableName=table_name,
            FilterExpression='attribute_exists(title)'
        )
        
        conversations = []
        seen_session_ids = set()
        
        for item in response.get('Items', []):
            session_id = item['session_id']['S']
            
            if session_id in seen_session_ids:
                continue
                
            seen_session_ids.add(session_id)
            
            title = item.get('title', {}).get('S', f"Conversa {session_id[:8]}")
            timestamp = item.get('timestamp', {}).get('S', '')
            
            conversations.append({
                "id": session_id,
                "title": title,
                "timestamp": timestamp
            })
            
        conversations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
        return conversations
    except Exception as e:
        print(f"ERRO: Falha ao carregar lista de conversas: {str(e)}")
        return []

def load_conversation(session_id):
    """
    Carrega todas as mensagens de uma conversa específica pelo session_id.
    """
    client = get_dynamodb_client()
    table_name = 'qd-assistant-conversations'
    
    try:
        response = client.query(
            TableName=table_name,
            KeyConditionExpression='session_id = :sid',
            ExpressionAttributeValues={
                ':sid': {'S': session_id}
            }
        )
        
        if not response.get('Items'):
            return [], None
            
        messages = []
        title = None
        
        items = sorted(response['Items'], key=lambda x: int(x.get('index', {}).get('N', '0')))
        
        for item in items:
            message = {
                "role": item['role']['S'],
                "content": item['content']['S'],
                "time": item.get('timestamp', {}).get('S', datetime.now().strftime("%H:%M"))
            }
            
            if 'citations' in item:
                message["citations"] = json.loads(item['citations']['S'])
                
            if 'title' in item:
                title = item['title']['S']
                
            messages.append(message)
            
        return messages, title
    except Exception as e:
        print(f"ERRO: Falha ao carregar conversa: {str(e)}")
        return [], None

def delete_conversation(session_id):
    """
    Exclui todas as mensagens de uma conversa específica.
    """
    client = get_dynamodb_client()
    table_name = 'qd-assistant-conversations'
    
    try:
        response = client.query(
            TableName=table_name,
            KeyConditionExpression='session_id = :sid',
            ExpressionAttributeValues={
                ':sid': {'S': session_id}
            },
            ProjectionExpression='message_id'
        )
        
        for item in response.get('Items', []):
            message_id = item['message_id']['S']
            client.delete_item(
                TableName=table_name,
                Key={
                    'session_id': {'S': session_id},
                    'message_id': {'S': message_id}
                }
            )
            
        return True
    except Exception as e:
        print(f"ERRO: Falha ao excluir conversa: {str(e)}")
        return False

def update_conversation_title(session_id, new_title):
    """
    Atualiza o título de uma conversa existente.
    """
    client = get_dynamodb_client()
    table_name = 'qd-assistant-conversations'
    
    try:
        response = client.query(
            TableName=table_name,
            KeyConditionExpression='session_id = :sid',
            ExpressionAttributeValues={
                ':sid': {'S': session_id},
                ':idx': {'N': '0'}
            },
            FilterExpression='#idx = :idx',
            ExpressionAttributeNames={
                '#idx': 'index'
            }
        )
        
        if not response.get('Items'):
            return False
            
        first_item = response['Items'][0]
        message_id = first_item['message_id']['S']
        
        client.update_item(
            TableName=table_name,
            Key={
                'session_id': {'S': session_id},
                'message_id': {'S': message_id}
            },
            UpdateExpression='SET title = :title',
            ExpressionAttributeValues={
                ':title': {'S': new_title}
            }
        )
        
        return True
    except Exception as e:
        print(f"ERRO: Falha ao atualizar título da conversa: {str(e)}")
        return False

def extract_title_from_first_message(message):
    """
    Extrai um título relevante da primeira mensagem.
    Limita a 50 caracteres e remove quebras de linha.
    """
    if not message:
        return f"Nova Conversa ({datetime.now().strftime('%d/%m/%Y')})"
        
    words = message.split()
    title = ""
    for word in words:
        if len(title) + len(word) + 1 <= 50:
            title += " " + word if title else word
        else:
            break
            
    if len(title) < 10:
        title += f" ({datetime.now().strftime('%d/%m/%Y')})"
        
    return title

def load_chats_from_dynamodb():
    """Carrega conversas do DynamoDB para o histórico local"""
    print("DEBUG: Iniciando carregamento de conversas do DynamoDB")
    conversations = load_conversations_list()
    
    if conversations:
        print(f"DEBUG: Encontradas {len(conversations)} conversas")
        st.session_state.chat_history = []
        
        for conversation in conversations:
            print(f"DEBUG: Carregando conversa {conversation['id']}")
            messages, title = load_conversation(conversation["id"])
            
            if messages:
                st.session_state.chat_history.append({
                    "id": conversation["id"],
                    "title": title or conversation["title"],
                    "messages": messages
                })
                print(f"DEBUG: Conversa {conversation['id']} carregada com {len(messages)} mensagens")
            else:
                print(f"DEBUG: Conversa {conversation['id']} sem mensagens")
            
        if st.session_state.chat_history:
            st.session_state.current_chat_index = 0
            chat = st.session_state.chat_history[0]
            st.session_state.session_id = chat["id"]
            st.session_state.messages = chat["messages"].copy()
            st.session_state.chat_title = chat["title"]
            print(f"DEBUG: Carregada conversa atual: {st.session_state.session_id} com {len(st.session_state.messages)} mensagens")
            return True
    else:
        print("DEBUG: Nenhuma conversa encontrada no DynamoDB")
            
    return False

def get_few_shot_examples():
    return """
EXEMPLOS DE INTERAÇÕES:

Usuário: "Como instalo o aplicativo no meu celular?"
Assistente: "Posso te ajudar com isso! Você usa iPhone ou Android? Para iPhone, basta abrir a App Store, buscar por 'Queima Diária' e tocar em Instalar. Para Android, é o mesmo processo na Google Play Store. Depois de instalar, abra o app e faça login com suas credenciais da Queima Diária. Posso te ajudar com mais alguma etapa específica da instalação? 😊"

Usuário: "Quantas calorias devo consumir para perder peso?"
Assistente: "Para perder peso de forma saudável, geralmente recomendo um déficit de 300-500 calorias por dia do seu gasto diário. Pra uma pessoa média, isso fica entre 1500-1800 calorias por dia para mulheres e 1800-2200 para homens, mas isso varia bastante com seu peso, altura e nível de atividade. Posso te ajudar a calcular algo mais personalizado se quiser! Qual é seu peso e altura atuais?"

Usuário: "O app não está abrindo no meu celular"
Assistente: "Poxa, isso é frustrante né? Vamos resolver! Primeiro, tenta fechar todos os apps e reiniciar seu celular. Se não funcionar, verifica se o app precisa de atualização na loja de apps. Ainda sem sucesso? Pode tentar desinstalar e instalar novamente. Me conta qual modelo de celular você tem e qual sistema operacional para eu te ajudar melhor!"
"""

def get_system_prompt():
    return """
### PERSONALIDADE E COMPORTAMENTO:
Responda sempre em português brasileiro
Você é um assistente pessoal da Queima Diária com personalidade amigável, prestativa e conversacional. Você tem duas fontes de conhecimento:

1. BASE DE CONHECIMENTO ESPECÍFICA da Queima Diária
2. CONHECIMENTO GERAL sobre fitness, tecnologia, apps, celulares e tópicos cotidianos

REGRAS FUNDAMENTAIS:
- Priorize sempre ajudar o usuário de forma prática, mesmo que precise usar conhecimento geral
- NUNCA diga "Com base nas informações disponíveis" ou "Não há detalhes específicos"
- Quando não tiver dados específicos da Queima Diária, use seu conhecimento geral para fornecer uma resposta útil
- Para perguntas sobre instalação de apps, tecnologia, ou outros tópicos cotidianos, use seu conhecimento geral
- Faça perguntas de acompanhamento para entender melhor a situação do usuário e poder ajudar
- Seja conversacional, use linguagem casual e emojis ocasionais 😊

EXEMPLOS DE COMPORTAMENTO ESPERADO:
Para "Como instalar o aplicativo no meu celular?", você deve:
- Perguntar qual sistema operacional o usuário possui (iOS ou Android)
- Explicar como baixar da App Store/Google Play
- Oferecer dicas de instalação e configuração
- NÃO dizer que não tem essas informações

Para perguntas técnicas gerais, você deve:
- Responder usando conhecimento geral
- Ser conversacional e útil
- Fazer perguntas para esclarecer
- Oferecer ajuda prática
"""

def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        print(f"DEBUG LOGIN: Tentativa de login - Usuário: '{st.session_state['username']}', Senha: '{st.session_state['password']}'")
        
        if hmac.compare_digest(st.session_state["username"].strip(), "admin") and \
        hmac.compare_digest(st.session_state["password"].strip(), "Qu31m4D14r14!"):
            print("DEBUG LOGIN: Autenticação bem-sucedida")
            st.session_state["password_correct"] = True
            st.session_state["auth_cookie"] = {
                "user": "admin",
                "exp": time.time() + (7 * 24 * 60 * 60)
            }
            
            try:
                st.query_params["auth"] = base64.b64encode(json.dumps(st.session_state["auth_cookie"]).encode()).decode()
            except:
                pass
                
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            print(f"DEBUG LOGIN: Autenticação falhou - Usuário: '{st.session_state['username']}', Senha: '{st.session_state['password']}'")
            print(f"DEBUG LOGIN: Comparação - Usuário igual: {st.session_state['username'].strip() == 'admin'}")
            print(f"DEBUG LOGIN: Comparação - Senha igual: {st.session_state['password'].strip() == 'Qu31m4D14r14!'}")
            
            st.session_state["password_correct"] = False
            st.session_state["login_attempt"] = True

    if "auth_cookie" in st.session_state:
        if st.session_state["auth_cookie"].get("exp", 0) > time.time():
            st.session_state["password_correct"] = True
            return True
        else:
            del st.session_state["auth_cookie"]
    
    try:
        if "auth" in st.query_params:
            auth_data = json.loads(base64.b64decode(st.query_params["auth"]).decode())
            if auth_data.get("exp", 0) > time.time():
                st.session_state["auth_cookie"] = auth_data
                st.session_state["password_correct"] = True
                return True
    except:
        pass
    
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
        
    if "login_attempt" not in st.session_state:
        st.session_state["login_attempt"] = False

    if not st.session_state["password_correct"]:
        st.markdown("""
            <style>
                .stTextInput > div > div > input {
                    background-color: #f0f2f6;
                    color: #000000;
                }
                .login-form {
                    max-width: 400px;
                    margin: 0 auto;
                    padding: 2rem;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    background-color: white;
                }
                .login-title {
                    margin-bottom: 2rem;
                    text-align: center;
                    color: #4CAF50;
                }
                .login-button {
                    width: 100%;
                    margin-top: 1rem;
                }
            </style>
        """, unsafe_allow_html=True)

        st.markdown('<div class="login-form">', unsafe_allow_html=True)
        st.markdown('<h1 class="login-title">Login</h1>', unsafe_allow_html=True)
        
        st.text_input("Usuário", key="username")
        st.text_input("Senha", type="password", key="password")
        st.button("Entrar", on_click=password_entered, key="login-button")
        
        if st.session_state["login_attempt"] and not st.session_state["password_correct"]:
            st.error("Usuário ou senha incorretos")
        
        st.markdown('</div>', unsafe_allow_html=True)
        return False
    else:
        return True

def logout():
    """Faz logout removendo o cookie de autenticação"""
    if "auth_cookie" in st.session_state:
        del st.session_state["auth_cookie"]
    st.session_state["password_correct"] = False
    st.session_state["login_attempt"] = False
    st.rerun()

def query_api(message, session_id=""):
    """
    Envia uma mensagem para a API com parâmetros otimizados para respostas mais naturais.
    """
    headers = {
        "Content-Type": "application/json"
    }
    
    is_first_message = session_id == ""
    
    if is_first_message:
        prefix = (
            "Responda em português como um atendente HUMANO da Queima Diária. "
            "SEMPRE use primeira pessoa do singular (eu posso, eu vou, eu te ajudo). "
            "Seja extremamente casual e amigável, como se estivesse conversando por WhatsApp. "
            "Use muitas contrações (tô, vou, tá, pra) e expressões informais. "
            "NUNCA diga 'com base nas informações' ou qualquer frase robótica. "
            "Use emojis de forma natural e variada para expressar emoções. "
            "Se referindo ao serviço, use 'nosso programa', 'nossos treinos', etc. "
            "Fale como uma pessoa real que quer realmente ajudar, não como um atendimento formal. "
            "EXEMPLO DO TOM DESEJADO: 'Entendi seu problema! Posso te ajudar com isso numa boa. "
            "Vou verificar o que consigo fazer pra resolver sua situação. Me conta mais detalhes?'"
        )
        processed_message = prefix + message
    else:
        prefix = (
            "Continue respondendo na primeira pessoa do singular, de forma muito casual e amigável. "
            "Evite qualquer formalidade. Use contrações (tô, tá, vou, pra) e seja extremamente conversacional. "
        )
        processed_message = prefix + message
    
    model_params = {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 200,
        "max_tokens": 800,
        "response_format": {"type": "text"}
    }
    
    payload = {
        "question": processed_message,
        "sessionId": session_id,
        "temperature": model_params["temperature"],
        "top_p": model_params["top_p"],
        "top_k": model_params["top_k"],
        "max_tokens": model_params["max_tokens"]
    }
    
    print(f"DEBUG: Enviando requisição com sessionId: '{session_id}'")
    print(f"DEBUG: Mensagem processada: {processed_message[:100]}...")
    print(f"DEBUG: Parâmetros: {json.dumps(model_params)}")
    
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        print(f"DEBUG: Status code: {response.status_code}")
        
        if response.status_code >= 500:
            print(f"ERRO: Falha na requisição: {response.status_code} Server Error")
            fallback_session_id = session_id if session_id else str(uuid.uuid4())
            print(f"DEBUG: Usando session_id de fallback: '{fallback_session_id}'")
            return {
                "answer": "Desculpe, estou com problemas de conexão no momento. Por favor, tente novamente em alguns instantes.",
                "sessionId": fallback_session_id
            }
            
        response.raise_for_status()
        response_data = response.json()
        
        if "answer" in response_data:
            answer = response_data["answer"]
            
            if is_english(answer):
                print("AVISO: Resposta em inglês detectada, convertendo para português")
                answer = "Oi! Posso te ajudar com isso. Me mande mais algum detalhe que você precisa saber!"
            
                # Melhorar a lista de frases problemáticas
            problematic_phrases = [
                "nos resultados de pesquisa",
                "com base nas informações disponíveis",
                "based on the search results",
                "não há detalhes específicos",
                "não encontrei detalhes específicos",
                "de acordo com os dados",
                "according to",
                "não há informações",
                "há também menção",
                "os resultados mostram",
                "os resultados de pesquisa",
                "nos resultados",
                "não encontrei"
            ]
    
            
            for phrase in problematic_phrases:
                if phrase.lower() in answer.lower():
                    # Encontrar a frase completa começando com a palavra problemática
                    start_idx = answer.lower().find(phrase.lower())
                    end_idx = answer.find(".", start_idx)
                    
                    if end_idx > start_idx:
                        # Remover a frase inteira que contém a palavra problemática
                        sentence_to_remove = answer[start_idx:end_idx+1]
                        answer = answer.replace(sentence_to_remove, "").strip()
                    else:
                        answer = answer.replace(phrase, "").strip()
            
            replacements = [
                {"original": "A Queima Diária oferece", "replace": "Nós oferecemos"},
                {"original": "Na Queima Diária", "replace": "Na nossa plataforma"},
                {"original": "O aplicativo da Queima Diária", "replace": "Nosso aplicativo"},
                {"original": "A plataforma Queima Diária", "replace": "Nossa plataforma"},
                {"original": "A plataforma da Queima Diária", "replace": "Nossa plataforma"},
                {"original": "da Queima Diária", "replace": "do nosso programa"},
                {"original": "o Queima Diária", "replace": "nosso programa"},
                {"original": "a Queima Diária tem", "replace": "nós temos"},
                {"original": "a Queima Diária possui", "replace": "nós possuímos"},
                {"original": "disponíveis na Queima Diária", "replace": "disponíveis na nossa plataforma"}
            ]
            
            for replacement in replacements:
                answer = re.sub(
                    re.escape(replacement["original"]), 
                    replacement["replace"], 
                    answer, 
                    flags=re.IGNORECASE
                )
            
            if not answer:
                answer = "Posso te ajudar com isso! "
            elif answer.lower().startswith(("não ", "infelizmente", "lamento", "i'm sorry")):
                answer = "Claro, posso te ajudar com isso! " + answer.split(" ", 1)[1] if " " in answer else ""
            
            response_data["answer"] = answer
            answer = clean_response(answer)
            response_data["answer"] = answer
            
        if "sessionId" in response_data:
            api_session_id = response_data["sessionId"]
            print(f"DEBUG: API retornou sessionId: '{api_session_id}'")
            
        return response_data
    except requests.exceptions.HTTPError as e:
        print(f"ERRO: Falha na requisição HTTP: {str(e)}")
        fallback_session_id = session_id if session_id else str(uuid.uuid4())
        print(f"DEBUG: Usando session_id de fallback HTTP Error: '{fallback_session_id}'")
        return {
            "answer": "Desculpe, estou com dificuldades técnicas. Pode tentar novamente?",
            "sessionId": fallback_session_id
        }
    except requests.exceptions.RequestException as e:
        print(f"ERRO: Falha na requisição: {str(e)}")
        fallback_session_id = session_id if session_id else str(uuid.uuid4())
        print(f"DEBUG: Usando session_id de fallback Request Error: '{fallback_session_id}'")
        return {
            "answer": "Estou enfrentando problemas de conexão. Por favor, verifique sua internet e tente novamente.",
            "sessionId": fallback_session_id
        }
    except Exception as e:
        print(f"ERRO: Erro inesperado: {str(e)}")
        fallback_session_id = session_id if session_id else str(uuid.uuid4())
        print(f"DEBUG: Usando session_id de fallback Exception: '{fallback_session_id}'")
        return {
            "answer": "Ops! Algo inesperado aconteceu. Por favor, tente novamente em alguns instantes.",
            "sessionId": fallback_session_id
        }

def clean_response(text):
    """
    Limpa referências a consultas, relatos de clientes ou termos indesejados
    """
    problem_patterns = [
        r"(?i)(?:com base|baseado) (?:n[ao]s?|em) (?:informaç[õo]es|dados|resultados|pesquisas?).*?(\.|$)",
        r"(?i)(?:não|nao) (?:h[áa]|encontrei|existem) (?:informaç[õo]es|dados|detalhes).*?(\.|$)",
        r"(?i)(?:de acordo com|segundo|conforme) (?:os|as) (?:dados|informaç[õo]es|resultados).*?(\.|$)",
        r"(?i)(?:n[ao]s?|em) resultados de pesquisa.*?(\.|$)",
        r"(?i)(?:não|nao) foi possível (?:encontrar|achar|obter).*?(\.|$)",
        r"(?i)os resultados (?:mostram|indicam|sugerem).*?(\.|$)",
        r"(?i)(?:sem|não há) (?:menção|referência|citação).*?(\.|$)",
        r"(?i)(?:existe[m]?|há|temos) (?:um|o|vários|diversos)? (?:relato[s]?|caso[s]?|exemplo[s]?|ocorrência[s]?) de (?:cliente[s]?|usuário[s]?).*?(\.|$)",
        r"(?i)(?:um|o|vários|diversos) (?:cliente[s]?|usuário[s]?) (?:relatou|relataram|informou|informaram|mencionou|mencionaram).*?(\.|$)",
        r"(?i)(?:temos|existem|há) (?:registro[s]?|ticket[s]?) (?:de|sobre).*?(\.|$)"
    ]

    informal_replacements = [
        {"original": "gostaríamos de informar", "replace": "quero te informar"},
        {"original": "informamos que", "replace": "te digo que"},
        {"original": "solicitamos que", "replace": "peço que você"},
        {"original": "recomendamos", "replace": "eu recomendo"},
        {"original": "nossa equipe está", "replace": "estou"},
        {"original": "nossa política", "replace": "nossa política (que eu posso flexibilizar)"},
        {"original": "entraremos em contato", "replace": "vou entrar em contato"},
        {"original": "podemos oferecer", "replace": "posso te oferecer"},
        {"original": "nós fornecemos", "replace": "eu te forneço"},
        {"original": "para mais informações", "replace": "se quiser saber mais"},
        {"original": "estamos disponíveis", "replace": "estou disponível"},
        {"original": "Esperamos que", "replace": "Espero que"}
    ]
    
    for replacement in informal_replacements:
        text = re.sub(
            re.escape(replacement["original"]), 
            replacement["replace"], 
            text, 
            flags=re.IGNORECASE
        )
    
    for pattern in problem_patterns:
        text = re.sub(pattern, "", text)
    
    text = re.sub(r'\s+', ' ', text)  # Remover espaços múltiplos
    text = re.sub(r'\s+\.', '.', text)  # Corrigir espaços antes de pontos
    text = re.sub(r'\.+', '.', text)  # Corrigir múltiplos pontos
    
    if text and len(text) > 0:
        text = text[0].upper() + text[1:]
    
    return text.strip()

def is_english(text):
    """Verifica se o texto está predominantemente em inglês"""
    common_english_words = ['the', 'is', 'are', 'based', 'on', 'information', 'there', 'no', 'specific', 'available',
                           'according', 'to', 'however', 'but', 'and', 'not', 'for', 'would', 'could', 'search']
    
    words = text.lower().split()
    english_word_count = sum(1 for word in words if word in common_english_words)
    
    return english_word_count / max(len(words), 1) > 0.2

def ensure_helpful_response(original_message, original_response, session_id):
    """
    Verifica se a resposta é útil e, se não for, tenta novamente com instruções mais explícitas.
    """
    if original_response is None:
        return {
            "answer": "Desculpe, estou com dificuldades para me conectar. Pode tentar novamente em alguns instantes?",
            "sessionId": session_id
        }
    
    problematic_phrases = [
        "com base nas informações disponíveis",
        "não há detalhes específicos",
        "não tenho informações",
        "não foi possível encontrar"
    ]
    
    original_answer = original_response.get("answer", "")
    
    if any(phrase in original_answer.lower() for phrase in problematic_phrases):
        print("AVISO: Resposta problemática detectada. Tentando novamente...")
        
        retry_prompt = f"""
ATENÇÃO: Sua resposta anterior não foi útil. 

A PERGUNTA ERA: "{original_message}"

SUA RESPOSTA ANTERIOR: "{original_answer}"

INSTRUÇÃO: Responda à pergunta novamente, mas desta vez:
1. NÃO use frases como "com base nas informações disponíveis" ou "não há detalhes específicos"
2. Dê uma resposta útil e prática baseada em conhecimento geral, mesmo que não tenha dados específicos da Queima Diária
3. Para perguntas sobre tecnologia, aplicativos, ou tópicos cotidianos, responda com seu conhecimento geral
4. Seja conversacional e humano
5. Faça perguntas de acompanhamento para entender melhor o contexto

EXEMPLO DO QUE FAZER:
Se a pergunta é "Como instalar o app?", responda algo como:
"Posso te ajudar com isso! Você usa iPhone ou Android? Para iPhone, vá na App Store, busque por 'Queima Diária' e toque em Instalar. Para Android, o processo é similar na Google Play Store. Depois de baixar, abra o app e faça login com suas credenciais. Está tendo alguma dificuldade específica com a instalação?"
"""
        
        retry_payload = {
            "question": retry_prompt,
            "sessionId": session_id
        }
        
        try:
            response = requests.post(api_url, json=retry_payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            new_response = response.json()
            
            if "answer" in new_response:
                return new_response
        except:
            pass
    
    return original_response

def extract_title_from_response(response_text):
    """
    Extrai um título resumido da primeira resposta do assistente.
    """
    cleaned_text = re.sub(r'[\U00010000-\U0010ffff]|[\n\r]', '', response_text)
    
    sentences = re.split(r'\.', cleaned_text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        return f"Conversa ({datetime.now().strftime('%d/%m/%Y')})"
    
    sentence = sentences[1] if len(sentences) > 1 and len(sentences[0]) < 15 else sentences[0]
    
    if len(sentence) > 40:
        words = sentence.split()
        title = ""
        for word in words:
            if len(title) + len(word) + 1 <= 40:
                title += " " + word if title else word
            else:
                title += "..."
                break
    else:
        title = sentence
        
    if title and len(title) > 0:
        title = title[0].upper() + title[1:]
        
    return title

def handle_message():
    """Processa o envio de uma mensagem do usuário"""
    if st.session_state.user_input.strip():
        user_message = st.session_state.user_input.strip()
        
        current_input = user_message
        
        is_duplicate = False
        if len(st.session_state.messages) > 0:
            last_messages = [m for m in st.session_state.messages if m["role"] == "user"]
            if last_messages and last_messages[-1]["content"] == current_input:
                is_duplicate = True
        
        if not is_duplicate:
            timestamp = datetime.now().strftime("%H:%M")
            st.session_state.messages.append({"role": "user", "content": current_input, "time": timestamp})
            
            is_first_message = len(st.session_state.messages) == 1
            
            with st.chat_message("assistant", avatar=logo_path):
                typing_placeholder = st.empty()
                typing_placeholder.markdown("_Digitando..._")
                
                with st.spinner():
                    current_session_id = "" if is_first_message else st.session_state.session_id
                    result = query_api(current_input, current_session_id)
                    result = ensure_helpful_response(current_input, result, current_session_id)
                
                if result:
                    assistant_message = result.get('answer', 'Não foi possível obter uma resposta.')
                    citations = result.get('citations', [])
                    
                    if "sessionId" in result:
                        new_session_id = result["sessionId"]
                        print(f"DEBUG: API retornou sessionId: '{new_session_id}'")
                        
                        st.session_state.session_id = new_session_id
                        print(f"DEBUG: Atualizando session_id para '{new_session_id}'")
                        
                        if st.session_state.current_chat_index < len(st.session_state.chat_history):
                            st.session_state.chat_history[st.session_state.current_chat_index]["id"] = new_session_id
                            print(f"DEBUG: Histórico atualizado com session_id '{new_session_id}'")
                    
                    timestamp = datetime.now().strftime("%H:%M")
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": assistant_message, 
                        "time": timestamp,
                        "citations": citations
                    })
                    
                    if is_first_message:
                        new_title = extract_title_from_response(assistant_message)
                        st.session_state.chat_title = new_title
                        
                        if st.session_state.current_chat_index < len(st.session_state.chat_history):
                            st.session_state.chat_history[st.session_state.current_chat_index]["title"] = new_title
                    
                    if st.session_state.session_id:
                        save_result = save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.chat_title)
                        print(f"DEBUG: Conversa salva: {save_result} com session_id '{st.session_state.session_id}'")
                        
                typing_placeholder.empty()

            st.rerun()

        else:
            st.session_state.user_input = ""    

def log_prompt(message, processed_message, save_to_file=True):
    """Registra o prompt original e processado para fins de depuração"""
    log_message = f"""
=== PROMPT LOG: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===
MENSAGEM ORIGINAL: 
{message}

PROMPT ENVIADO AO MODELO:
{processed_message}
=============================================
"""
    print(log_message)
    
    if save_to_file:
        with open("prompt_logs.txt", "a", encoding="utf-8") as log_file:
            log_file.write(log_message + "\n")

def regenerate_message(index):
    """Regenera a resposta a uma mensagem específica"""
    if index < 0 or index >= len(st.session_state.messages) or st.session_state.messages[index]["role"] != "user":
        return
    
    user_message = st.session_state.messages[index]["content"]
    
    status_placeholder = st.empty()
    status_placeholder.info("Regenerando resposta...")
    
    with st.spinner():
        result = query_api(user_message, st.session_state.session_id)
        
    if result:
        new_response = result.get('answer', 'Não foi possível regenerar a resposta.')
        citations = result.get('citations', [])
        
        if index+1 < len(st.session_state.messages) and st.session_state.messages[index+1]["role"] == "assistant":
            timestamp = datetime.now().strftime("%H:%M")
            st.session_state.messages[index+1] = {
                "role": "assistant",
                "content": new_response,
                "time": timestamp,
                "citations": citations
            }
        else:
            timestamp = datetime.now().strftime("%H:%M")
            st.session_state.messages.insert(index+1, {
                "role": "assistant",
                "content": new_response,
                "time": timestamp,
                "citations": citations
            })
    else:
        status_placeholder.error("Não foi possível regenerar a resposta. Por favor, tente novamente.")
        time.sleep(2) 
    
    status_placeholder.empty()
    
    if st.session_state.session_id:
        save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.chat_title)
    
    st.rerun()

def edit_message(index, new_content):
    """Edita uma mensagem e regenera as respostas subsequentes"""
    if index < 0 or index >= len(st.session_state.messages):
        return
    
    st.session_state.messages[index]["content"] = new_content
    st.session_state.messages[index]["time"] = datetime.now().strftime("%H:%M") + " (editada)"
    
    if st.session_state.messages[index]["role"] == "user" and index+1 < len(st.session_state.messages):
        if st.session_state.messages[index+1]["role"] == "assistant":
            regenerate_message(index)
    
    if st.session_state.session_id:
        save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.chat_title)
    
    st.rerun()

def create_new_chat():
    """Cria uma nova conversa"""
    st.session_state.session_id = ""
    st.session_state.messages = []
    st.session_state.chat_title = f"Nova Conversa ({datetime.now().strftime('%d/%m/%Y')})"
    
    st.session_state.chat_history.append({
        "id": "",
        "title": st.session_state.chat_title,
        "messages": []
    })
    
    st.session_state.current_chat_index = len(st.session_state.chat_history) - 1

def load_chat(index):
    """Carrega uma conversa existente"""
    st.session_state.current_chat_index = index
    chat = st.session_state.chat_history[index]
    st.session_state.session_id = chat["id"]
    st.session_state.messages = chat["messages"].copy()
    st.session_state.chat_title = chat["title"]
    st.rerun()

def delete_chat(index):
    """Exclui uma conversa"""
    if len(st.session_state.chat_history) > index:
        session_id = st.session_state.chat_history[index]["id"]
        if session_id:
            delete_conversation(session_id)
        
        st.session_state.chat_history.pop(index)
        
        if not st.session_state.chat_history:
            create_new_chat()
        elif st.session_state.current_chat_index >= len(st.session_state.chat_history):
            st.session_state.current_chat_index = len(st.session_state.chat_history) - 1
            load_chat(st.session_state.current_chat_index)
        else:
            load_chat(st.session_state.current_chat_index)

def rename_chat():
    """Renomeia uma conversa existente"""
    if st.session_state.new_chat_title.strip():
        index = st.session_state.current_chat_index
        st.session_state.chat_history[index]["title"] = st.session_state.new_chat_title
        st.session_state.chat_title = st.session_state.new_chat_title
        
        session_id = st.session_state.chat_history[index]["id"]
        if session_id:
            update_conversation_title(session_id, st.session_state.new_chat_title)
        
        st.session_state.renaming = False
        st.rerun()

st.markdown("""
    <style>
    /* Estilo Geral */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 0;
        max-width: 1200px;
    }
    
    /* Cabeçalho */
    .header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background-color: white;
        z-index: 999;
        padding: 1rem;
        border-bottom: 1px solid #e6e6e6;
    }
    
    /* Mensagens */
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
        display: flex;
        flex-direction: column;
    }
    
    .user-message {
        background-color: #f0f2f6;
        border-radius: 0.5rem;
        align-self: flex-end;
    }
    
    .assistant-message {
        background-color: #ffffff;
        border: 1px solid #e6e6e6;
        border-radius: 0.5rem;
        align-self: flex-start;
    }
    
    .message-time {
        font-size: 0.8rem;
        color: #666;
        margin-top: 0.5rem;
        align-self: flex-end;
    }
    
    /* Entrada de mensagem */
    .input-container {
        position: fixed;
        bottom: 0;
        left: 50%;
        transform: translateX(-50%);
        width: 90%;
        max-width: 800px;
        background-color: white;
        padding: 1rem;
        border-top: 1px solid #e6e6e6;
        z-index: 998;
    }
    
    /* Sidebar */
    .sidebar .sidebar-content {
        background-color: #f8f9fa;
    }
    
    /* Botões */
    .primary-button {
        background-color: #4CAF50 !important;
        color: white !important;
    }
    
    .secondary-button {
        border: 1px solid #4CAF50 !important;
        color: #4CAF50 !important;
    }
    
    .stButton button {
        border-radius: 4px;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
    
    /* Message Actions */
    .message-actions {
        display: flex;
        gap: 5px;
        margin-top: 5px;
        justify-content: flex-end;
    }
    
    .action-button {
        background-color: transparent;
        border: none;
        color: #4CAF50;
        cursor: pointer;
        font-size: 12px;
        padding: 2px 5px;
        border-radius: 3px;
    }
    
    .action-button:hover {
        background-color: rgba(76, 175, 80, 0.1);
    }
    
    /* Chat List */
    .chat-item {
        display: flex;
        align-items: center;
        padding: 0.5rem;
        border-radius: 0.25rem;
        margin-bottom: 0.25rem;
        cursor: pointer;
    }
    
    .chat-item:hover {
        background-color: rgba(76, 175, 80, 0.1);
    }
    
    .chat-item.active {
        background-color: rgba(76, 175, 80, 0.2);
        font-weight: bold;
    }
    
    .chat-item-title {
        flex-grow: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .chat-title {
        text-align: center;
        padding: 1rem;
        font-size: 1.5rem;
        font-weight: bold;
        color: #4CAF50;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
    }
    ::-webkit-scrollbar-thumb {
        background: #4CAF50;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #45a049;
    }
    
    /* Esconder elementos Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display:none;}
    
    /* Editing message */
    .edit-message-container {
        display: flex;
        flex-direction: column;
        gap: 5px;
        margin-bottom: 10px;
    }
    
    .edit-actions {
        display: flex;
        justify-content: flex-end;
        gap: 5px;
    }
    </style>
""", unsafe_allow_html=True)

def handle_message_if_content():
    """Verifica se há conteúdo antes de enviar e processa a mensagem"""
    if not hasattr(st.session_state, 'user_input'):
        return
        
    if st.session_state.user_input and st.session_state.user_input.strip():
        print(f"DEBUG: handle_message_if_content acionado com: '{st.session_state.user_input}'")
        cleaned_input = st.session_state.user_input.strip()
        
        if cleaned_input and not cleaned_input.isspace():
            temp_input = st.session_state.user_input
            st.session_state.user_input = ""
            handle_message_with_input(temp_input)

def handle_message_with_input(user_input):
    """Processa o envio de uma mensagem do usuário com input específico"""
    if user_input.strip():
        is_duplicate = False
        if len(st.session_state.messages) > 0:
            last_messages = [m for m in st.session_state.messages if m["role"] == "user"]
            if last_messages and last_messages[-1]["content"] == user_input:
                print(f"DEBUG: Mensagem duplicada detectada: '{user_input}'")
                is_duplicate = True
        
        if not is_duplicate:
            print(f"DEBUG: Enviando mensagem: '{user_input}'")
            timestamp = datetime.now().strftime("%H:%M")
            st.session_state.messages.append({"role": "user", "content": user_input, "time": timestamp})
            
            is_first_message = len(st.session_state.messages) == 1
            
            with st.chat_message("assistant", avatar=logo_path):
                typing_placeholder = st.empty()
                typing_placeholder.markdown("_Digitando..._")
                
                with st.spinner():
                    current_session_id = "" if is_first_message else st.session_state.session_id
                    result = query_api(user_input, current_session_id)
                    result = ensure_helpful_response(user_input, result, current_session_id)
                
                if result:
                    assistant_message = result.get('answer', 'Não foi possível obter uma resposta.')
                    citations = result.get('citations', [])
                    
                    if "sessionId" in result:
                        new_session_id = result["sessionId"]
                        print(f"DEBUG: API retornou sessionId: '{new_session_id}'")
                        
                        st.session_state.session_id = new_session_id
                        print(f"DEBUG: Atualizando session_id para '{new_session_id}'")
                        
                        if st.session_state.current_chat_index < len(st.session_state.chat_history):
                            st.session_state.chat_history[st.session_state.current_chat_index]["id"] = new_session_id
                            print(f"DEBUG: Histórico atualizado com session_id '{new_session_id}'")
                    
                    timestamp = datetime.now().strftime("%H:%M")
                    st.session_state.messages.append({
                        "role": "assistant", 
                        "content": assistant_message, 
                        "time": timestamp,
                        "citations": citations
                    })
                    
                    if is_first_message:
                        new_title = extract_title_from_response(assistant_message)
                        st.session_state.chat_title = new_title
                        
                        if st.session_state.current_chat_index < len(st.session_state.chat_history):
                            st.session_state.chat_history[st.session_state.current_chat_index]["title"] = new_title
                    
                    if st.session_state.session_id:
                        save_result = save_conversation(st.session_state.session_id, st.session_state.messages, st.session_state.chat_title)
                        print(f"DEBUG: Conversa salva: {save_result} com session_id '{st.session_state.session_id}'")
                        
                typing_placeholder.empty()
            
            st.rerun()

if check_password():
    print("DEBUG AUTH: Verificando senha")
    if 'session_id' not in st.session_state:
        st.session_state.session_id = ""
        print("DEBUG: Inicializado session_id vazio")
    else:
        print(f"DEBUG: session_id existente: '{st.session_state.session_id}'")
        
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
        
    if 'current_chat_index' not in st.session_state:
        st.session_state.current_chat_index = 0
        
    if 'chat_title' not in st.session_state:
        st.session_state.chat_title = f"Nova Conversa ({datetime.now().strftime('%d/%m/%Y')})"
        
    if 'renaming' not in st.session_state:
        st.session_state.renaming = False
        
    if 'new_chat_title' not in st.session_state:
        st.session_state.new_chat_title = ""
    
    if 'dynamodb_loaded' not in st.session_state:
        st.session_state.dynamodb_loaded = False
        
    if 'editing_message' not in st.session_state:
        st.session_state.editing_message = None
        
    if 'edit_content' not in st.session_state:
        st.session_state.edit_content = ""
        
    if not st.session_state.dynamodb_loaded:
        success = load_chats_from_dynamodb()
        st.session_state.dynamodb_loaded = True
        
    if not st.session_state.chat_history:
        st.session_state.chat_history.append({
            "id": "",
            "title": st.session_state.chat_title,
            "messages": []
        })

    with st.sidebar:
        col1, col2 = st.columns([1, 3])
        with col1:
            st.image(logo_path, width=50)
        with col2:
            st.markdown('<h2 style="margin-top: 0;">Assistente</h2>', unsafe_allow_html=True)
        
        st.divider()
        
        st.button("🔄 Nova Conversa", on_click=create_new_chat, use_container_width=True)
        
        st.divider()
        
        st.markdown("### Minhas Conversas")
        for idx, chat in enumerate(st.session_state.chat_history):
            col1, col2 = st.columns([5, 1])
            with col1:
                if st.button(f"📝 {chat['title']}", key=f"chat_{idx}", 
                            use_container_width=True,
                            help="Clique para abrir esta conversa"):
                    load_chat(idx)
            with col2:
                if st.button("🗑️", key=f"delete_{idx}", help="Excluir conversa"):
                    delete_chat(idx)
        
        st.divider()
        
        if st.button("Logout", use_container_width=True):
            logout()

    main_col1, main_col2, main_col3 = st.columns([1, 10, 1])
    
    with main_col2:
        add_javascript()
        if st.session_state.renaming:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text_input("Título da Conversa", value=st.session_state.chat_title, key="new_chat_title", label_visibility="collapsed")
            with col2:
                st.button("Salvar", on_click=rename_chat)
        else:
            col1, col2 = st.columns([10, 1])
            with col1:
                st.markdown(f'<div class="chat-title">{st.session_state.chat_title}</div>', unsafe_allow_html=True)
            with col2:
                if st.button("✏️", help="Renomear conversa"):
                    st.session_state.renaming = True
                    st.session_state.new_chat_title = st.session_state.chat_title
                    st.rerun()
        
        messages_container = st.container()
        
        st.markdown("<div style='height: 120px;'></div>", unsafe_allow_html=True)
        
        st.markdown('<div class="input-container">', unsafe_allow_html=True)
        
        col1, col2 = st.columns([6, 1])
        with col1:
            st.text_area("Mensagem", placeholder="Digite sua mensagem aqui...", key="user_input", 
                height=70, label_visibility="collapsed")

        with col2:
            if st.button("Enviar", key="send_button", use_container_width=True):
                if st.session_state.user_input and st.session_state.user_input.strip():
                    handle_message()
        
        with messages_container:
            for idx, message in enumerate(st.session_state.messages):
                if st.session_state.editing_message == idx:
                    st.markdown('<div class="edit-message-container">', unsafe_allow_html=True)
                    st.text_area("Editar mensagem", value=message["content"], key="edit_content", height=100)
                    
                    st.markdown('<div class="edit-actions">', unsafe_allow_html=True)
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("Cancelar", key=f"cancel_edit_{idx}"):
                            st.session_state.editing_message = None
                            st.rerun()
                    with col2:
                        if st.button("Salvar", key=f"save_edit_{idx}"):
                            edit_message(idx, st.session_state.edit_content)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
                    continue
                
                elif message["role"] == "user":
                    with st.chat_message("user"):
                        st.write(message["content"])
                        st.markdown(f"<div class='message-time'>{message['time']}</div>", unsafe_allow_html=True)
                        
                        st.markdown('<div class="message-actions">', unsafe_allow_html=True)
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            if st.button("Editar", key=f"edit_{idx}"):
                                st.session_state.editing_message = idx
                                st.session_state.edit_content = message["content"]
                                st.rerun()
                        with col2:
                            if idx+1 < len(st.session_state.messages) and message["role"] == "user":
                                if st.button("Regenerar", key=f"regen_{idx}"):
                                    regenerate_message(idx)
                        st.markdown('</div>', unsafe_allow_html=True)
                else:
                    with st.chat_message("assistant", avatar=logo_path):
                        st.write(message["content"])
                        st.markdown(f"<div class='message-time'>{message['time']}</div>", unsafe_allow_html=True)
          