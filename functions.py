import boto3
import json
import uuid
from datetime import datetime
import os

PROFILE_NAME = os.environ.get('AWS_PROFILE', 'edn173')

def get_boto3_client(service_name, region_name='us-east-2', profile_name='edn173'):
    """
    Retorna um cliente do serviço AWS especificado.
    
    Tenta usar o perfil especificado para desenvolvimento local primeiro.
    Se falhar, assume que está em uma instância EC2 e usa as credenciais do IAM role.
    """
    try:
        session = boto3.Session(profile_name=profile_name, region_name=region_name)
        client = session.client(service_name)
        if service_name == 'sts':
            client.get_caller_identity()
        return client
    except Exception as e:
        print(f"INFO: Não foi possível usar o perfil local '{profile_name}', tentando credenciais do IAM role: {str(e)}")
        try:
            session = boto3.Session(region_name=region_name)
            return session.client(service_name)
        except Exception as e:
            print(f"ERRO: Falha ao criar cliente boto3: {str(e)}")
            return None

def generate_chat_prompt(user_message, conversation_history=None):
    """
    Gera um prompt de chat completo com histórico de conversa
    """
    system_prompt = """
    Você é um assistente virtual amigável e prestativo. Sua função é auxiliar o usuário de forma clara, 
    educada e eficiente. Forneça respostas diretas e úteis para as perguntas ou solicitações do usuário.
    """

    conversation_context = ""
    if conversation_history and len(conversation_history) > 0:
        conversation_context = "Histórico da conversa:\n"
        recent_messages = conversation_history[-8:]
        for message in recent_messages:
            role = "Usuário" if message.get('role') == 'user' else "Assistente"
            conversation_context += f"{role}: {message.get('content')}\n"
        conversation_context += "\n"

    full_prompt = f"{system_prompt}\n\n{conversation_context}Usuário: {user_message}\n\nAssistente:"
    
    return full_prompt

def invoke_bedrock_model(prompt, model_params=None):
    """
    Invoca um modelo no Amazon Bedrock com os parâmetros especificados
    """
    if model_params is None:
        model_params = {
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 200,
            "max_tokens": 800
        }
    
    bedrock_runtime = get_boto3_client('bedrock-runtime')
    
    if not bedrock_runtime:
        return {
            "error": "Não foi possível conectar ao serviço Bedrock.",
            "answer": "Erro de conexão com o modelo.",
            "sessionId": str(uuid.uuid4())
        }
    
    try:
        inference_profile_arn = "arn:aws:bedrock:us-east-2:851614451056:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": model_params["max_tokens"],
            "temperature": model_params["temperature"],
            "top_p": model_params["top_p"],
            "top_k": model_params["top_k"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        })
        
        response = bedrock_runtime.invoke_model(
            modelId=inference_profile_arn,
            body=body,
            contentType="application/json",
            accept="application/json"
        )
        
        response_body = json.loads(response['body'].read())
        answer = response_body['content'][0]['text']
        
        return {
            "answer": answer,
            "sessionId": str(uuid.uuid4())
        }
        
    except Exception as e:
        print(f"ERRO: Falha na invocação do modelo Bedrock: {str(e)}")
        return {
            "error": str(e),
            "answer": f"Ocorreu um erro ao processar sua solicitação: {str(e)}. Por favor, tente novamente.",
            "sessionId": str(uuid.uuid4())
        }