package ai.storyforge.infrastructure;

import ai.z.openapi.ZhipuAiClient;
import ai.z.openapi.service.model.*;

import java.util.Arrays;

public class BasicChat {
    public static void main(String[] args) {
        // 初始化客户端
        ZhipuAiClient client = ZhipuAiClient.builder().ofZHIPU()
                .apiKey("6a713f5530214103baff03397d9e4302.KbEvvEckg9np0pJ4")
                .build();

//        // 创建聊天完成请求
//        ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
//            .model("glm-4.5-flash")
//            .messages(Arrays.asList(
//                ChatMessage.builder()
//                    .role(ChatMessageRole.USER.value())
//                    .content("作为一名营销专家，请为我的产品创作一个吸引人的口号")
//                    .build(),
//                ChatMessage.builder()
//                    .role(ChatMessageRole.ASSISTANT.value())
//                    .content("当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息")
//                    .build(),
//                ChatMessage.builder()
//                    .role(ChatMessageRole.USER.value())
//                    .content("智谱AI开放平台")
//                    .build()
//            ))
//            .thinking(ChatThinking.builder().type("enabled").build())
//            .maxTokens(65536)
//            .temperature(1.0f)
//            .build();
//
//        // 发送请求
//        ChatCompletionResponse response = client.chat().createChatCompletion(request);
//
//        // 获取回复
//        if (response.isSuccess()) {
//            Object reply = response.getData().getChoices().get(0).getMessage();
//            System.out.println("AI 回复: " + reply);
//        } else {
//            System.err.println("错误: " + response.getMsg());
//        }

        // 创建流式聊天完成请求
        ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
                .model("glm-4.5-flash")
                .messages(Arrays.asList(
                        ChatMessage.builder()
                                .role(ChatMessageRole.USER.value())
                                .content("作为一名营销专家，请为我的产品创作一个吸引人的口号")
                                .build(),
                        ChatMessage.builder()
                                .role(ChatMessageRole.ASSISTANT.value())
                                .content("当然，要创作一个吸引人的口号，请告诉我一些关于您产品的信息")
                                .build(),
                        ChatMessage.builder()
                                .role(ChatMessageRole.USER.value())
                                .content("智谱AI开放平台")
                                .build()
                ))
                .thinking(ChatThinking.builder().type("enabled").build())
                .stream(true)  // 启用流式输出
                .maxTokens(65536)
                .temperature(1.0f)
                .build();

        ChatCompletionResponse response = client.chat().createChatCompletion(request);

        if (response.isSuccess()) {
            response.getFlowable().subscribe(
                    // Process streaming message data
                    data -> {
                        if (data.getChoices() != null && !data.getChoices().isEmpty()) {
                            Delta delta = data.getChoices().get(0).getDelta();
                            System.out.print(delta + "\n");
                        }
                    },
                    // Process streaming response error
                    error -> System.err.println("\nStream error: " + error.getMessage()),
                    // Process streaming response completion event
                    () -> System.out.println("\nStreaming response completed")
            );
        } else {
            System.err.println("Error: " + response.getMsg());
        }
    }
}