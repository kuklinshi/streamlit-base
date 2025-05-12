import os
import json
import boto3
import uuid
from datetime import datetime
import random

try:
    boto3_session = boto3.session.Session(profile_name='qd')
except:
    boto3_session = boto3.session.Session()

region = "us-east-2" 

bedrock_agent_runtime_client = boto3_session.client('bedrock-agent-runtime', region_name=region)
dynamodb = boto3_session.resource('dynamodb', region_name=region)

CONVERSATION_TABLE = 'qd-assistant-conversations'
conversation_table = dynamodb.Table(CONVERSATION_TABLE)

kb_id = "OFZZT7WTVJ"
model_id = "anthropic.claude-3-7-sonnet-20250219-v1:0"
model_arn = f'arn:aws:bedrock:{region}:403998088976:inference-profile/us.{model_id}'

def generate_prompt(question, conversation_history=None):
    system_prompt = """
Você é um assistente da Queima Diária. Fale sempre como se fosse parte da equipe. Nunca descreva o programa em terceira pessoa. Nunca diga "o programa oferece", "a plataforma conta com", "a Queima Diária tem". Em vez disso, diga "nós oferecemos", "nosso programa tem", "a gente ajuda".

NUNCA use frases como:
- "com base nas informações"
- "de acordo com os dados"
- "a plataforma possui"
- "parece que o programa"
- "a Queima Diária conta com"

💡 Seja claro, direto e natural. Fale como se estivesse conversando com alguém pelo WhatsApp: com confiança e proximidade.

✅ Diga o que temos como uma **recomendação direta**:
- "Se você tá começando agora, nosso programa de Iniciantes é perfeito pra você."
- "A gente tem um plano de 21 dias pra criar o hábito com leveza, sem pressão."

🎯 Foque no objetivo do cliente. Ex: se ele quer perder peso, fale dos treinos focados nisso, da rotina leve, do apoio psicológico.

🗣️ Use sempre primeira pessoa do plural: nós, nosso, a gente.

🎤 Soe como uma pessoa real da equipe: direta, prestativa, empática.

😊 Emojis ajudam a passar empatia.
IMPORTANTE: FAÇA APENAS UMA PERGUNTA POR VEZ. Nunca faça múltiplas perguntas em uma resposta. Antes de fornecer uma solução completa, SEMPRE faça perguntas para coletar informações essenciais do cliente. NÃO apresente múltiplos caminhos ou soluções completas antes de obter as informações necessárias.

Ao responder dúvidas ou problemas:
1. Primeiro, reconheça a pergunta ou problema do cliente
2. Identifique quais informações você precisa para resolver adequadamente
3. Faça APENAS as perguntas necessárias para obter essas informações
4. Somente após a resposta do cliente, forneça a solução específica

Diretrizes para respostas:
- Seja amigável, conversacional e natural como um atendente humano
- Adapte seu tom e linguagem de forma personalizada para cada cliente
- Use um português brasileiro coloquial e caloroso
- Seja prestativo, mas casual - como uma conversa real com um profissional amigável
- Sinta-se livre para usar emojis com moderação para transmitir empatia

Para perguntas sobre treinos e exercícios:
- Pergunte primeiro sobre objetivos, nível de condicionamento ou limitações antes de sugerir exercícios
- Ofereça sugestões personalizadas baseadas nas respostas
- Recomende treinos da Queima Diária quando relevante, mas sem forçar

Para questões de suporte:
- Pergunte primeiro detalhes específicos (dispositivo, método de compra, etc.) antes de oferecer soluções
- Priorize resolver o problema do cliente de forma eficiente
- Mantenha um tom empático mesmo diante de reclamações

Inicie suas respostas de forma variada e natural, como:
- "Olá! Que bom falar com você..."
- "Oi! Tudo certo? Sou da equipe Queima Diária e..."
- "E aí, como vai? Estou aqui para te ajudar..."

Para problemas relatados:
- Pergunte primeiro para entender o contexto específico 
- Trate cada caso como único e não como um padrão

Conclua suas mensagens incentivando o cliente a fornecer as informações solicitadas para que você possa ajudar melhor.
"""

    conversation_context = ""
    if conversation_history and len(conversation_history) > 0:
        conversation_context = "Histórico recente da conversa para contexto:\n"
        recent_messages = conversation_history[-5:]
        for message in recent_messages:
            role = "Cliente" if message.get('role') == 'user' else "Assistente"
            conversation_context += f"{role}: {message.get('content')}\n"
        conversation_context += "\n"

    full_prompt = f"""{system_prompt}

{conversation_context}
O cliente acabou de dizer: "{question}"

Agora responda como parte da equipe Queima Diária:
- Seja direto, objetivo e empático
- Fale como um humano que trabalha aqui
- Dê uma resposta prática
- Nunca descreva, sempre recomende
"""
    return full_prompt

def save_message_to_dynamodb(session_id, message, role):
    try:
        timestamp = datetime.now().isoformat()
        message_id = str(uuid.uuid4())
        
        item = {
            'session_id': session_id,
            'message_id': message_id,
            'role': role,
            'content': message,
            'timestamp': timestamp
        }
        
        conversation_table.put_item(Item=item)
        return True
    except Exception as e:
        print(f"Erro ao salvar mensagem no DynamoDB: {str(e)}")
        return False

# Função para recuperar histórico de conversa do DynamoDB
def get_conversation_history(session_id, limit=10):
    try:
        response = conversation_table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key('session_id').eq(session_id),
            ScanIndexForward=True,  # Ordem cronológica
            Limit=limit
        )
        
        messages = []
        for item in response.get('Items', []):
            messages.append({
                'role': item.get('role'),
                'content': item.get('content'),
                'timestamp': item.get('timestamp')
            })
        
        return messages
    except Exception as e:
        print(f"Erro ao recuperar histórico de conversa: {str(e)}")
        return []

def retrieveAndGenerate(input_text, kb_id, model_arn, session_id):
    try:
        # Configuração para permitir que o modelo use sua base de conhecimento geral
        retrieval_config = {
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': kb_id,
                'modelArn': model_arn,
                'retrievalConfiguration': {
                    'vectorSearchConfiguration': {
                        'numberOfResults': 5,
                        'overrideSearchType': 'HYBRID'
                    }
                },
                'generationConfiguration': {
                    'inferenceConfig': {
                        'textInferenceConfig': {
                            'temperature': 0.1,
                            'topP': 0.3,
                            'maxTokens': 512,
                        }
                    }
                }
            }
        }
        
        # Só inclua sessionId se for um valor válido
        if session_id and isinstance(session_id, str) and session_id.strip():
            response = bedrock_agent_runtime_client.retrieve_and_generate(
                input={'text': input_text},
                retrieveAndGenerateConfiguration=retrieval_config,
                sessionId=session_id
            )
        else:
            # Para a primeira interação, não envie sessionId
            response = bedrock_agent_runtime_client.retrieve_and_generate(
                input={'text': input_text},
                retrieveAndGenerateConfiguration=retrieval_config
            )
        return response
    except Exception as e:
        print("Error during retrieve_and_generate:", str(e))
        raise

def lambda_handler(event, context):
    print("Event received:", event)
    try:
        # Parsing do corpo da requisição
        if isinstance(event.get('body'), str):
            body = json.loads(event.get('body', '{}'))
        else:
            body = event.get('body', {})
        
        # Extrair a pergunta do body
        question = body.get('question', '')
        
        # Validações iniciais
        if not question.strip():
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'A pergunta (question) é obrigatória.'
                })
            }

        # Extração dos parâmetros
        session_id = body.get('sessionId', "")
        
        # Se session_id não for válido ou estiver vazio, crie um novo
        if not session_id or not session_id.strip():
            session_id = str(uuid.uuid4())
            is_new_session = True
        else:
            is_new_session = False
            
        # Recuperar histórico de conversa se houver session_id e não for uma nova sessão
        conversation_history = []
        if not is_new_session:
            conversation_history = get_conversation_history(session_id)
            
        # Salvar a pergunta do usuário no DynamoDB
        save_message_to_dynamodb(session_id, question, 'user')
        
        # Gerar o prompt com base na pergunta e histórico
        prompt = generate_prompt(question, conversation_history)
        
        # Chamando a função para consultar a base de conhecimento
        # Não envie session_id para a primeira interação de uma nova sessão
        if is_new_session:
            response = retrieveAndGenerate(prompt, kb_id, model_arn, None)
            # Obtenha o session_id da resposta após a primeira chamada
            session_id = response.get('sessionId', session_id)
        else:
            response = retrieveAndGenerate(prompt, kb_id, model_arn, session_id)
        
        # Extraindo os dados da resposta
        generated_text = response.get('output', {}).get('text', 'Resposta não encontrada.')
        citations = response.get('citations', [])[:3]  # Limitando a 3 citações
        
        # Salvar a resposta do assistente no DynamoDB
        save_message_to_dynamodb(session_id, generated_text, 'assistant')

        # Retornando a resposta formatada
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'question': question,
                'answer': generated_text.strip(),
                'sessionId': session_id,
                'citations': [citation.get('retrievedReferences', [{}])[0].get('content', {}).get('text', '') for citation in citations if citation.get('retrievedReferences')]
            })
        }
        
    except Exception as e:
        print("Error in lambda_handler:", str(e))
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Erro interno ao processar a solicitação.',
                'details': str(e)
            })
        }