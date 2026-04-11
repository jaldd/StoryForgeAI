package ai.storyforge.application.port.outbound;

public interface EmbeddingClient {
    float[] embed(String text);
}
