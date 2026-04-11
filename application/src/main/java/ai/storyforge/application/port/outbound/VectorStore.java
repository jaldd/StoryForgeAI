package ai.storyforge.application.port.outbound;

import java.util.List;

public interface VectorStore {
    void store(String id, float[] embedding, String metadata);
    List<String> search(float[] queryEmbedding, int topK);
}
