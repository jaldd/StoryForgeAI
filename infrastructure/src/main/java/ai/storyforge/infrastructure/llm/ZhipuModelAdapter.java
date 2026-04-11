package ai.storyforge.infrastructure.llm;

import ai.storyforge.application.port.outbound.ModelGateway;
import ai.z.openapi.ZhipuAiClient;
import ai.z.openapi.service.model.*;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

import java.util.Arrays;

@Component
public class ZhipuModelAdapter implements ModelGateway {

    private final ZhipuAiClient zhipuAiClient;

    public ZhipuModelAdapter(ZhipuAiClient zhipuAiClient) {
        this.zhipuAiClient = zhipuAiClient;
    }

    @Override
    public String chat(String prompt) {
        ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
                .model("glm-4-flash")
                .messages(Arrays.asList(
                        ChatMessage.builder()
                                .role(ChatMessageRole.USER.value())
                                .content(prompt)
                                .build()
                ))
                .maxTokens(4096)
                .temperature(0.7f)
                .build();

        ChatCompletionResponse response = zhipuAiClient.chat().createChatCompletion(request);

        if (response.isSuccess() && response.getData() != null && !response.getData().getChoices().isEmpty()) {
            Object content = response.getData().getChoices().get(0).getMessage().getContent();
            return content != null ? content.toString() : "";
        }

        return "Error: " + response.getMsg();
    }

    @Override
    public AiMessage chat(UserMessage message) {
        String response = chat(message.singleText());
        return new AiMessage(response);
    }

    @Override
    public Flux<String> chatStream(String prompt) {
        Sinks.Many<String> sink = Sinks.many().unicast().onBackpressureBuffer();

        ChatCompletionCreateParams request = ChatCompletionCreateParams.builder()
                .model("glm-4-flash")
                .messages(Arrays.asList(
                        ChatMessage.builder()
                                .role(ChatMessageRole.USER.value())
                                .content(prompt)
                                .build()
                ))
                .stream(true)
                .maxTokens(4096)
                .temperature(0.7f)
                .build();

        ChatCompletionResponse response = zhipuAiClient.chat().createChatCompletion(request);

        if (response.isSuccess()) {
            response.getFlowable().subscribe(
                    data -> {
                        if (data.getChoices() != null && !data.getChoices().isEmpty()) {
                            Delta delta = data.getChoices().get(0).getDelta();
                            if (delta != null && delta.getContent() != null) {
                                String content = delta.getContent().toString();
                                System.out.println(content);
                                if (!content.isEmpty()) {
                                    sink.tryEmitNext(content);
                                }
                            }
                        }
                    },
                    error -> {
                        System.err.println("Stream error: " + error.getMessage());
                        sink.tryEmitError(error);
                    },
                    () -> {
                        System.out.println("Stream completed");
                        sink.tryEmitComplete();
                    }
            );
        } else {
            sink.tryEmitError(new RuntimeException("Error: " + response.getMsg()));
        }

        return sink.asFlux();
    }
}
