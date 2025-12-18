import os
import json
import httpx
import openai
 
 
class FormulaChatClient:
    def __init__(self, base_url: str, api_key: str):
        """初始化 Formula 客户端"""
        self.base_url = base_url
        self.api_key = api_key
        self.openai = openai.Client(
            base_url=base_url,
            api_key=api_key,
        )
        self.httpx = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        self.model = "kimi-k2-thinking"
 
    def get_tools(self, formula_uri: str):
        """从 Formula API 获取工具定义"""
        response = self.httpx.get(f"/formulas/{formula_uri}/tools")
        response.raise_for_status()  # 检查 HTTP 状态码
        
        try:
            return response.json().get("tools", [])
        except json.JSONDecodeError as e:
            print(f"错误: 无法解析响应为 JSON (状态码: {response.status_code})")
            print(f"响应内容: {response.text[:500]}")
            raise
 
    def call_tool(self, formula_uri: str, function: str, args: dict):
        """调用官方工具"""
        response = self.httpx.post(
            f"/formulas/{formula_uri}/fibers",
            json={"name": function, "arguments": json.dumps(args)},
        )
        response.raise_for_status()  # 检查 HTTP 状态码
        fiber = response.json()
        
        if fiber.get("status", "") == "succeeded":
            return fiber["context"].get("output") or fiber["context"].get("encrypted_output")
        
        if "error" in fiber:
            return f"Error: {fiber['error']}"
        if "error" in fiber.get("context", {}):
            return f"Error: {fiber['context']['error']}"
        return "Error: Unknown error"
 
    def close(self):
        """关闭客户端连接"""
        self.httpx.close()
 
 
# 初始化客户端
base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
api_key = os.getenv("MOONSHOT_API_KEY")
 
if not api_key:
    raise ValueError("MOONSHOT_API_KEY 环境变量未设置，请先设置 API 密钥")
 
print(f"Base URL: {base_url}")
print(f"API Key: {api_key[:10]}...{api_key[-10:] if len(api_key) > 20 else api_key}\n")
 
client = FormulaChatClient(base_url, api_key)
 
# 定义要使用的官方工具 Formula URI
formula_uris = [
    "moonshot/date:latest",
    "moonshot/web-search:latest"
]
 
# 加载所有工具定义并建立映射
print("正在加载官方工具...")
all_tools = []
tool_to_uri = {}  # function.name -> formula_uri 的映射
 
for uri in formula_uris:
    try:
        tools = client.get_tools(uri)
        for tool in tools:
            func = tool.get("function")
            if func:
                func_name = func.get("name")
                if func_name:
                    tool_to_uri[func_name] = uri
                    all_tools.append(tool)
                    print(f"  已加载工具: {func_name} from {uri}")
    except Exception as e:
        print(f"  警告: 加载工具 {uri} 失败: {e}")
        continue
 
print(f"总共加载 {len(all_tools)} 个工具\n")
 
if not all_tools:
    raise ValueError("未能加载任何工具，请检查 API 密钥和网络连接")
 
# 初始化消息列表
messages = [
    {
        "role": "system",
        "content": "你是 Kimi，一个专业的新闻分析师。你擅长收集、分析和整理信息，生成高质量的新闻报告。",
    },
]
 
# 用户请求生成今日新闻报告
user_request = "请帮我生成一份今日新闻报告，包含重要的科技、经济和社会新闻。"
messages.append({
    "role": "user",
    "content": user_request
})
 
print(f"用户请求: {user_request}\n")
 
 
max_iterations = 10  # 防止无限循环
for iteration in range(max_iterations):
    # 调用模型
    try:
        completion = client.openai.chat.completions.create(
            model=client.model,
            messages=messages,
            max_tokens=1024 * 32,
            tools=all_tools,
            temperature=1.0,
        )
    except openai.AuthenticationError as e:
        print(f"认证错误: {e}")
        print("请检查 API key 是否正确，以及 API key 是否有权限访问该端点")
        raise
    except Exception as e:
        print(f"调用模型时发生错误: {e}")
        raise
    
    # 获取响应
    message = completion.choices[0].message
    
    # 打印思考过程
    if hasattr(message, "reasoning_content"):
        print(f"=============第 {iteration + 1} 轮思考开始=============")
        reasoning = getattr(message, "reasoning_content")
        if reasoning:
            print(reasoning[:500] + "..." if len(reasoning) > 500 else reasoning)
        print(f"=============第 {iteration + 1} 轮思考结束=============\n")
    
    # 添加 assistant 消息到上下文（保留 reasoning_content）
    messages.append(message)
    
    # 如果模型没有调用工具，说明对话结束
    if not message.tool_calls:
        print("=============最终回答=============")
        print(message.content)
        break
    
    # 处理工具调用
    print(f"模型决定调用 {len(message.tool_calls)} 个工具:\n")
    
    for tool_call in message.tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        
        print(f"调用工具: {func_name}")
        print(f"参数: {json.dumps(args, ensure_ascii=False, indent=2)}")
        
        # 获取对应的 formula_uri
        formula_uri = tool_to_uri.get(func_name)
        if not formula_uri:
            print(f"错误: 找不到工具 {func_name} 对应的 Formula URI")
            continue
        
        # 调用工具
        result = client.call_tool(formula_uri, func_name, args)
        
        # 打印结果（截断过长内容）
        if len(str(result)) > 200:
            print(f"工具结果: {str(result)[:200]}...\n")
        else:
            print(f"工具结果: {result}\n")
        
        # 添加工具结果到消息列表
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": func_name,
            "content": result
        }
        messages.append(tool_message)
 
print("\n对话完成！")
 
# 清理资源
client.close()