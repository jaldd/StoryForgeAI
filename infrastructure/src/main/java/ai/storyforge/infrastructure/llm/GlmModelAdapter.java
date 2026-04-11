package ai.storyforge.infrastructure.llm;

import ai.storyforge.application.port.outbound.ModelGateway;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.chat.StreamingChatLanguageModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.chat.response.StreamingChatResponseHandler;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;

//@Component
public class GlmModelAdapter implements ModelGateway {

    private final ChatLanguageModel chatModel;
    private final StreamingChatLanguageModel streamingChatModel;

    public GlmModelAdapter(ChatLanguageModel chatModel, StreamingChatLanguageModel streamingChatModel) {
        this.chatModel = chatModel;
        this.streamingChatModel = streamingChatModel;
    }

    @Override
    public String chat(String prompt) {
        return chatModel.chat(prompt);
    }

    @Override
    public AiMessage chat(UserMessage message) {
        return chatModel.chat(message).aiMessage();
    }

    @Override
    public Flux<String> chatStream(String prompt) {
        Sinks.Many<String> sink = Sinks.many().unicast().onBackpressureBuffer();
        
        streamingChatModel.chat(prompt, new StreamingChatResponseHandler() {
            @Override
            public void onPartialResponse(String partialResponse) {
                System.out.print("res:"+partialResponse);
                sink.tryEmitNext(partialResponse);
            }

            @Override
            public void onCompleteResponse(ChatResponse completeResponse) {
                sink.tryEmitComplete();
            }

            @Override
            public void onError(Throwable error) {
                sink.tryEmitError(error);
            }
        });

        return sink.asFlux();
    }
}
